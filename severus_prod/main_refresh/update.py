# satvvik: Add resumable main refresh without changing the original loaders or schema.
import argparse
import datetime
from email.message import EmailMessage
import fcntl
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid

import mysql.connector

from inputs import STAGES, fingerprint_inputs, prepare_downloads, resolve_inputs, run_stage, verify_inputs
from model import Cache, SPECS, RefreshError, Table, qualified, quote
from reconcile import capture_existing, merge_table, prepare_desired, schema_signature, validate_result

LOG = logging.getLogger('main_refresh')
CONFIGS = {'db_pred': 'interaction_sources_pred.json', 'db_published': 'interaction_sources_published_pred.json',
           'db_k_graph': 'interaction_sources_kgraph.json'}


# satvvik: Save checkpoints atomically so an interruption cannot leave a partial state file.
def save_state(path, state):
    descriptor, temporary = tempfile.mkstemp(prefix=Path(path).name + '.part-', dir=str(Path(path).parent))
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(state, output, indent=2, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(str(Path(path).parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def connect(settings, database=None):
    args = {'host': settings['host'], 'port': settings['port'], 'user': settings['user'],
            'password': settings['password'], 'autocommit': False, 'connection_timeout': 15}
    if database:
        args['database'] = database
    if settings.get('socket'):
        args['unix_socket'] = settings['socket']
    return mysql.connector.connect(**args)


def bootstrap(conn, database, schema_path):
    cursor = conn.cursor()
    try:
        # satvvik: Match the schema's utf8mb4 defaults when creating a database.
        cursor.execute('CREATE DATABASE IF NOT EXISTS ' + quote(database)
                       + ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        cursor.execute('USE ' + quote(database))
        cursor.execute('SELECT @@SESSION.sql_mode')
        mode = cursor.fetchone()[0]
        # satvvik: Allow the existing schema's zero-date defaults, then restore the session mode.
        cursor.execute('SET SESSION sql_mode=%s',
                       (','.join(value for value in mode.split(',') if value not in ('NO_ZERO_DATE', 'NO_ZERO_IN_DATE')),))
        try:
            for statement in re.finditer(r'CREATE TABLE IF NOT EXISTS `[^`]+` \(.*?\) ENGINE[^;]+;',
                                         Path(schema_path).read_text(), re.S):
                cursor.execute(statement.group(0))
        finally:
            cursor.execute('SET SESSION sql_mode=%s', (mode,))
    finally:
        cursor.close()
    conn.commit()


def check_version(conn):
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT VERSION()')
        version = cursor.fetchone()[0]
    finally:
        cursor.close()
    numbers = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
    if not numbers or tuple(map(int, numbers.groups())) < (8, 0, 13) or 'mariadb' in version.lower():
        raise RefreshError('Main refresh requires MySQL 8.0.13 or newer')


def reference_name(key, token):
    return 'hippip_main_' + key[:12] + '_' + token[:12]


# satvvik: Reset staging tables only; the existing production tables remain populated.
def ensure_reference(conn, target, reference, tables):
    if not re.fullmatch(r'hippip_main_[0-9a-f]{12}_[0-9a-f]{12}', reference) or reference == target:
        raise RefreshError('Unsafe isolated-database name')
    cursor = conn.cursor()
    try:
        cursor.execute('CREATE DATABASE IF NOT EXISTS ' + quote(reference))
        for table in tables:
            cursor.execute('CREATE TABLE IF NOT EXISTS ' + qualified(reference, table.name)
                           + ' LIKE ' + qualified(target, table.name))
            cursor.execute('TRUNCATE TABLE ' + qualified(reference, table.name))
    finally:
        cursor.close()
    conn.commit()


def cleanup_reference(conn, state, target):
    reference = state['reference']
    if reference != reference_name(state['key'], state['token']) or reference == target:
        raise RefreshError('Refusing to remove an unowned isolated database')
    cursor = conn.cursor()
    try:
        cursor.execute('DROP DATABASE IF EXISTS ' + quote(reference))
    finally:
        cursor.close()
    conn.commit()


def new_state(key, rawfiles, root, workflow, source_config):
    token = uuid.uuid4().hex
    return {'version': 1, 'key': key, 'token': token, 'reference': reference_name(key, token),
            'phase': 'preparing', 'rawfiles': str(Path(rawfiles).resolve()), 'root': str(Path(root).resolve()),
            'workflow': str(Path(workflow).resolve()), 'source_config': str(Path(source_config).resolve()),
            'completed_stages': [], 'reference_ready': False, 'baseline_ready': False}


def run_refresh(options, settings):
    root = Path(options.root).resolve()
    workflow = Path(options.workflow).resolve()
    if workflow.name not in CONFIGS:
        raise RefreshError('Workflow directory must be db_pred, db_published, or db_k_graph')
    launcher = workflow / '1_main.sh'
    source_config = Path(options.sources or root / 'config' / CONFIGS[workflow.name]).resolve()
    rawfiles = Path(options.rawfiles or '/data01/backup/rawfiles/' + datetime.date.today().isoformat()).resolve()
    state_directory = workflow / 'main_state'
    state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn, reference_conn, cache, lock_file = None, None, None, None
    lock_name = None
    try:
        conn = connect(settings)
        check_version(conn)
        bootstrap(conn, options.database, root / 'config/dbstructure.sql')
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT @@server_uuid,DATABASE()')
            server, database = cursor.fetchone()
            key = hashlib.sha256((server + ':' + database).encode()).hexdigest()
            lock_name = 'hippip_main_' + key[:40]
            # satvvik: Prevent concurrent main refreshes from writing to the same database.
            cursor.execute('SELECT GET_LOCK(%s,0)', (lock_name,))
            if cursor.fetchone()[0] != 1:
                lock_name = None
                raise RefreshError('Another main refresh is running for this database')
        finally:
            cursor.close()
        lock_file = (state_directory / (key + '.lock')).open('a')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = state_directory / (key + '.json')
        state = json.loads(state_path.read_text()) if state_path.is_file() else None
        if state and (state.get('version') != 1 or state.get('key') != key
                      or not re.fullmatch(r'[0-9a-f]{32}', state.get('token', ''))
                      or state.get('reference') != reference_name(key, state['token'])):
            raise RefreshError('Unsupported or invalid main-refresh checkpoint')
        if state and state.get('phase') not in ('preparing', 'loading', 'upserting', 'deleting', 'completed'):
            raise RefreshError('Invalid refresh phase in the checkpoint')
        if state and not options.restart and state['phase'] != 'completed':
            if state['root'] != str(root) or state['workflow'] != str(workflow) or state['source_config'] != str(source_config):
                raise RefreshError('The saved project or source configuration differs; use --restart for a new run')
            if options.rawfiles and state['rawfiles'] != str(rawfiles):
                raise RefreshError('The saved input directory differs; use --restart for a new run')
            if state.get('baseline_ready') and not (state_directory / state['token'] / 'records.sqlite3').is_file():
                raise RefreshError('The resume cache is missing; use --restart to rebuild it')
            completed = state.get('completed_stages', [])
            if completed != [stage[0] for stage in STAGES[:len(completed)]]:
                raise RefreshError('The saved stage order is invalid')
            if state['phase'] in ('upserting', 'deleting') and len(completed) != len(STAGES):
                raise RefreshError('Cannot reconcile incomplete original-loader output')
        tables = [Table(conn, database, name) for name in SPECS]
        conn.commit()
        # satvvik: Skip loaders and writes when both saved inputs and current data still match.
        if state and state['phase'] == 'completed' and not options.restart and not options.force:
            if state['rawfiles'] == str(rawfiles) and state['source_config'] == str(source_config):
                try:
                    verify_inputs(state['manifest'])
                    cache = Cache(state_directory / state['token'] / 'records.sqlite3')
                    validate_result(conn, database, tables, cache)
                    cleanup_reference(conn, state, database)
                    LOG.info('Main refresh already complete for unchanged inputs and data; no records were rewritten')
                    return
                except (RefreshError, FileNotFoundError):
                    if cache:
                        cache.close()
                        cache = None
                    conn.commit()
        if state and options.restart:
            cleanup_reference(conn, state, database)
            state = None
        if not state or state['phase'] == 'completed':
            state = new_state(key, rawfiles, root, workflow, source_config)
            save_state(state_path, state)
        elif options.force:
            raise RefreshError('--force cannot replace inputs in an unfinished run; use --restart to start a new snapshot')
        job = state_directory / state['token']
        job.mkdir(mode=0o700, exist_ok=True)
        if cache is None:
            cache = Cache(job / 'records.sqlite3')
        # satvvik: Pin source files and loader versions for this run before capturing existing data.
        if state['phase'] == 'preparing':
            if not options.skip_downloads:
                prepare_downloads(launcher, state['rawfiles'], options.force)
            state['inputs'] = resolve_inputs(root, state['rawfiles'], state['source_config'], job)
            state['manifest'] = fingerprint_inputs(state['inputs'], root, launcher, state['source_config'])
            state['schema_signature'] = schema_signature(conn, database, tables)
            state['phase'] = 'loading'
            save_state(state_path, state)
        verify_inputs(state['manifest'])
        if schema_signature(conn, database, tables) != state['schema_signature']:
            raise RefreshError('The table definitions changed since this run started')
        if not state['baseline_ready']:
            capture_existing(conn, database, tables, cache)
            state['baseline_ready'] = True
            save_state(state_path, state)
        if not state['reference_ready']:
            ensure_reference(conn, database, state['reference'], tables)
            state['reference_ready'] = True
            save_state(state_path, state)
        # satvvik: Run unchanged loaders in staging; resume at the first unfinished source stage.
        if state['phase'] == 'loading':
            reference_conn = connect(settings, state['reference'])
            for stage in STAGES:
                if stage[0] in state['completed_stages']:
                    LOG.info('Resume: %s already imported successfully', stage[0])
                    continue
                run_stage(stage, root, job, state['reference'], state['inputs'], settings, reference_conn)
                state['completed_stages'].append(stage[0])
                save_state(state_path, state)
            verify_inputs(state['manifest'])
            prepare_desired(reference_conn, state['reference'], tables, cache)
            state['phase'] = 'upserting'
            save_state(state_path, state)
        # satvvik: Apply complete loader output in batches, preserving IDs and unchanged timestamps.
        if state['phase'] == 'upserting':
            for table in tables:
                merge_table(conn, database, table, cache, options.batch_size)
            state['phase'] = 'deleting'
            save_state(state_path, state)
        # satvvik: Remove missing records only after every source and all upserts finish successfully.
        if state['phase'] == 'deleting':
            verify_inputs(state['manifest'])
            for table in reversed(tables):
                merge_table(conn, database, table, cache, options.batch_size, delete=True)
            validate_result(conn, database, tables, cache)
            if schema_signature(conn, database, tables) != state['schema_signature']:
                raise RefreshError('The refresh altered a table definition')
            state['phase'] = 'completed'
            save_state(state_path, state)
        if reference_conn:
            reference_conn.close()
            reference_conn = None
        cleanup_reference(conn, state, database)
        LOG.info('Completed main refresh in %s; schema unchanged, source output reconciled and obsolete records removed', database)
    finally:
        if reference_conn:
            reference_conn.close()
        if cache:
            cache.close()
        if conn:
            try:
                conn.rollback()
                if lock_name:
                    cursor = conn.cursor()
                    cursor.execute('SELECT RELEASE_LOCK(%s)', (lock_name,))
                    cursor.fetchone()
                    cursor.close()
            finally:
                conn.close()
        if lock_file:
            lock_file.close()


# satvvik: Retain existing email notices; delivery failures must not undo a completed refresh.
def notify(options, succeeded, detail=''):
    if os.environ.get('UPDATE_EMAIL_NOTICES', '1') == '0':
        return
    try:
        launcher = Path(options.workflow) / '1_main.sh'
        match = re.search(r'^EMAIL="([^"\n]+)"', launcher.read_text(), re.M)
        recipient = os.environ.get('MAIN_EMAIL') or (match.group(1) if match else '')
        binary = shutil.which('sendmail')
        if not recipient or not binary:
            LOG.warning('Email notice skipped: sendmail or recipient is unavailable')
            return
        message = EmailMessage()
        message['From'] = 'noreply@dbmi.pitt.edu'
        message['To'] = recipient
        if succeeded:
            message['Subject'] = 'Update: Data Push to ' + options.database + ' Completed'
            message.set_content('Dear Team,\n\nThe data has been successfully pushed to the ' + options.database
                                + ' database. Thank you for your attention.\n\nBest regards,\nYour Hippip Script\n')
        else:
            message['Subject'] = 'Update FAILED for ' + options.database + ' on ' + socket.gethostname()
            message.set_content('The update script failed.\nError: ' + detail + '\nCheck logs and rerun to resume.\n')
        subprocess.run([binary, '--', recipient], input=message.as_bytes(), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=30)
    except Exception as error:
        LOG.warning('Email notice failed (%s); the refresh result is unchanged', type(error).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Refresh main data with the original loaders and unchanged table definitions.')
    parser.add_argument('--root', default=os.environ.get('HIPPIP_ROOT', str(Path(__file__).resolve().parents[2])))
    parser.add_argument('--workflow', required=True)
    parser.add_argument('-d', '--database', default=os.environ.get('PRODUCTION_DB'))
    parser.add_argument('-u', '--user', default=os.environ.get('DB_USER'))
    parser.add_argument('--host', default=os.environ.get('DB_HOST', 'localhost'))
    parser.add_argument('--port', type=int, default=os.environ.get('DB_PORT', '3306'))
    parser.add_argument('--socket', default=os.environ.get('DB_SOCKET'))
    parser.add_argument('--rawfiles', default=os.environ.get('HIPPIP_RAWFILES'))
    parser.add_argument('--sources')
    parser.add_argument('--skip-downloads', action='store_true')
    parser.add_argument('-f', '--force', action='store_true')
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--batch-size', type=int, default=os.environ.get('MAIN_BATCH_SIZE', '5000'))
    options = parser.parse_args(argv)
    if not 1 <= options.batch_size <= 50000:
        parser.error('--batch-size must be between 1 and 50000')
    if not options.database:
        default = Path(options.workflow).name
        options.database = input('MySQL Database [' + default + ']: ').strip() or default
    if not options.user:
        options.user = input('MySQL Username: ').strip()
    password = os.environ['DB_PASS'] if 'DB_PASS' in os.environ else getpass.getpass('MySQL Password: ')
    workflow = Path(options.workflow)
    workflow.mkdir(parents=True, exist_ok=True)
    log_directory = workflow / 'main_logs'
    log_directory.mkdir(exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(log_directory / 'main.log')])
    settings = {'host': options.host, 'port': options.port, 'user': options.user,
                'password': password, 'socket': options.socket}
    try:
        run_refresh(options, settings)
        notify(options, True)
        return 0
    except KeyboardInterrupt:
        LOG.warning('Interrupted. Rerun the same command to resume saved work.')
        return 130
    except Exception as error:
        # satvvik: Redact credentials before errors reach logs or email.
        message = str(error).replace(password, '[redacted]') if password else str(error)
        LOG.error('FAILED: %s. Rerun the same command to resume; only the active target batch is rolled back.', message)
        notify(options, False, message)
        return 1


if __name__ == '__main__':
    sys.exit(main())
