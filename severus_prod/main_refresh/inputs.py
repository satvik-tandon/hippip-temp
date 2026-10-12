# satvvik: Prepare fixed source inputs and run original loaders with isolated connections.
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from model import RefreshError, qualified

LOG = logging.getLogger('main_refresh')

# satvvik: Keep the original loader order; table lists are cleared only in the staging database.
STAGES = (
    ('genes', 'Genes/update.pl', 'gene_info', ('genes',)),
    ('go', 'GO/update.pl', 'gene2go', ('go_annotations', 'go_terms')),
    ('psimi', 'psimi-ontology/psi-mi_cv.pl', 'mi.obo', ('psimi_ontologies',)),
    ('hprd', 'Cross/HPRD/update.pl', 'hprd_mapping', ('entrez2hprd',)),
    ('ensembl', 'Cross/Ensembl/update.pl', 'gene2ensembl', ('entrez2ensembls',)),
    ('uniprot', 'Cross/Uniprot/update.pl', 'uniprot', ('entrez2uniprots',)),
    ('pathways', 'Pathways/update.pl', 'reactome', ('pathways', 'entrez2pathways')),
    ('gwas', 'GWAS/update.pl', 'gwas', ('GWAS',)),
    ('pdb', 'pdb/update.py', 'uniprot', ('entrez2pdbs',)),
    ('diseases', 'kegg/insert_diseases.py', 'diseases', ('diseases', 'entrez2diseases')),
    ('drugbank', 'Drugs/Drugbank/drugbank.pl', 'drugbank', ('drugs', 'entrez2drugs', 'atc_codes')),
    ('fda', 'Drugs/Drugbank/update_fda_approvals.py', 'drugbank', ()),
    ('interactions', 'Interactions/update.py', 'sources',
     ('interaction2externals', 'interaction2types', 'interaction2detections',
      'interaction2scores', 'interaction2publications', 'interactions')),
    ('direct', 'Interactions/insert_valid_direct_interactions.py', None, ('valid_direct_interactions',)),
    ('partners', 'Interactions/insert_valid_direct_interacting_partners.py', None, ('valid_direct_interacting_partners',)),
    ('enrichment', 'go-enrichment/enrichment_analysis.py', 'go_obo', ('entrez2enriched_go_terms',)),
)

DEPENDENCIES = ('Interactions/interaction.py', 'Interactions/interactions.py', 'Interactions/mitab.py',
                'Interactions/psimi.py', 'Interactions/hippip.py', 'Drugs/Drugbank/Update.pm')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_urls(launcher):
    match = re.search(r'^SOURCE_FILES=\((.*?)^\)', Path(launcher).read_text(), re.M | re.S)
    if not match:
        raise RefreshError('Cannot find the original source URL list')
    return [match.group(1) for line in match.group(1).splitlines()
            if (match := re.match(r'\s*"([^"]+)"', line))]


# satvvik: Validate each temporary download before replacing a complete cached file.
def atomic_download(url, target, force=False):
    target = Path(target)
    if target.is_file() and target.stat().st_size and not force:
        if target.suffix == '.gz':
            subprocess.run(['gzip', '-t', str(target)], check=True)
        elif target.suffix == '.zip':
            with zipfile.ZipFile(target) as archive:
                if archive.testzip():
                    raise RefreshError('Corrupt cached ZIP: ' + str(target))
        return
    descriptor, temporary = tempfile.mkstemp(prefix=target.name + '.part-', dir=str(target.parent))
    os.close(descriptor)
    try:
        subprocess.run(['wget', '--tries=3', '--timeout=60', '-nv', '-O', temporary, url], check=True)
        if not Path(temporary).stat().st_size:
            raise RefreshError('Empty download: ' + target.name)
        if target.suffix == '.gz':
            subprocess.run(['gzip', '-t', temporary], check=True)
        elif target.suffix == '.zip':
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip():
                    raise RefreshError('Corrupt ZIP download: ' + target.name)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare_downloads(launcher, rawfiles, force=False):
    rawfiles = Path(rawfiles)
    rawfiles.mkdir(parents=True, exist_ok=True)
    for url in source_urls(launcher):
        target = rawfiles / url.rsplit('/', 1)[-1]
        LOG.info('Preparing %s', target.name)
        atomic_download(url, target, force)
        if target.suffix == '.gz':
            destination = target.with_suffix('')
            if force or not destination.is_file() or destination.stat().st_mtime_ns < target.stat().st_mtime_ns:
                descriptor, temporary = tempfile.mkstemp(prefix=destination.name + '.part-', dir=str(rawfiles))
                os.close(descriptor)
                try:
                    # satvvik: Keep the previous decompressed file intact if extraction fails.
                    with gzip.open(target, 'rb') as source, open(temporary, 'wb') as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    os.replace(temporary, destination)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        elif target.suffix == '.zip':
            with zipfile.ZipFile(target) as archive:
                base = rawfiles.resolve()
                for member in archive.infolist():
                    destination = (rawfiles / member.filename).resolve()
                    if base not in destination.parents and destination != base:
                        raise RefreshError('ZIP member escapes the input directory')
                archive.extractall(rawfiles)
    candidates = sorted(path for path in rawfiles.glob('BIOGRID-ALL-*.mitab.txt') if path.name != 'BIOGRID-ALL.mitab.txt')
    if len(candidates) > 1:
        raise RefreshError('Multiple BioGRID releases exist; use an input directory containing one release')
    if candidates:
        os.replace(candidates[0], rawfiles / 'BIOGRID-ALL.mitab.txt')
    legacy = rawfiles / 'full'
    candidates = sorted(rawfiles.glob('gwas-catalog*-full.tsv'))
    if legacy.is_file():
        os.replace(legacy, rawfiles / 'gwascatalog.txt')
    elif candidates:
        os.replace(candidates[0], rawfiles / 'gwascatalog.txt')


def resolve_inputs(root, rawfiles, config_path, job):
    root, rawfiles, job = Path(root), Path(rawfiles), Path(job)
    inputs = {
        'gene_info': rawfiles / 'gene_info', 'gene2go': rawfiles / 'gene2go',
        'gene2ensembl': rawfiles / 'gene2ensembl', 'uniprot': rawfiles / 'HUMAN_9606_idmapping.dat',
        'mi.obo': rawfiles / 'mi.obo', 'reactome': rawfiles / 'UniProt2Reactome.txt',
        'gwas': rawfiles / 'gwascatalog.txt', 'go_obo': rawfiles / 'go-basic.obo',
        'hprd_mapping': root / 'static/HPRD_ID_MAPPINGS.txt',
        'diseases': root / 'static/diseases.kegg', 'drugbank': rawfiles.parent / 'DRUGS/full_database.xml',
    }
    sources = json.loads(Path(config_path).read_text())
    if not sources:
        raise RefreshError('The interaction-source configuration is empty')
    for index, source in enumerate(sources):
        filename = Path(source['filename'])
        # satvvik: Replace the changing latest link with this run's fixed input directory.
        if '/latest/' in str(filename):
            filename = rawfiles / filename.name
        filename = filename.resolve()
        source['filename'] = str(filename)
        inputs['interaction_' + str(index)] = filename
    for name, path in inputs.items():
        if not path.is_file() or not path.stat().st_size:
            raise RefreshError('Missing or empty input ' + name + ': ' + str(path))
    snapshot = job / 'interaction_sources.json'
    snapshot.write_text(json.dumps(sources, indent=2) + '\n')
    snapshot.chmod(0o600)
    inputs['sources'] = snapshot
    return {name: str(path.resolve()) for name, path in inputs.items()}


# satvvik: Hash source data and loader code so resume cannot mix different versions.
def fingerprint_inputs(inputs, root, launcher, config_path):
    files = dict(inputs)
    files['source_config'] = str(config_path)
    files['launcher'] = str(launcher)
    for _, script, _, _ in STAGES:
        files['loader:' + script] = str(Path(root) / 'scripts' / script)
    for script in DEPENDENCIES:
        files['helper:' + script] = str(Path(root) / 'scripts' / script)
    for path in Path(__file__).parent.glob('*.py'):
        files['refresh:' + path.name] = str(path)
    result = {}
    for name, filename in sorted(files.items()):
        path = Path(filename)
        result[name] = {'path': str(path.resolve()), 'sha256': file_hash(path), 'size': path.stat().st_size}
    return result


def verify_inputs(manifest):
    for item in manifest.values():
        path = Path(item['path'])
        if not path.is_file() or path.stat().st_size != item['size'] or file_hash(path) != item['sha256']:
            raise RefreshError('A saved input or loader changed; resume stopped: ' + str(path))


# satvvik: Redirect authentication and connections without editing the original Python loaders.
def python_adapter(directory):
    source = (
        'import getpass, os, mysql.connector\n'
        '_original_connect = mysql.connector.connect\n'
        'def _connect(*args, **kwargs):\n'
        '    if args:\n'
        '        raise RuntimeError("Positional database connections are not supported")\n'
        '    requested = kwargs.get("db", kwargs.get("database"))\n'
        '    if requested != os.environ["MAIN_REFERENCE_DB"]:\n'
        '        raise RuntimeError("A legacy loader attempted to leave its isolated database")\n'
        '    kwargs.update(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]), '
        'user=os.environ["DB_USER"], passwd=os.environ["DB_PASS"])\n'
        '    if os.environ.get("DB_SOCKET"):\n'
        '        kwargs["unix_socket"] = os.environ["DB_SOCKET"]\n'
        '    return _original_connect(**kwargs)\n'
        'mysql.connector.connect = _connect\n'
        'getpass.getpass = lambda *args, **kwargs: os.environ["DB_PASS"]\n'
    )
    source = '# satvvik: Keep legacy Python loaders in their isolated import database.\n' + source
    (directory / 'sitecustomize.py').write_text(source)


# satvvik: Adjust connection settings in private Perl copies, preserving their SQL and parsing.
def perl_adapter(script, directory, reference):
    source = Path(script).read_text()
    connection = re.compile(r'^(?![ \t]*#)([^\n]*?)DBI->connect\("dbi:mysql:[^"]*",\$user,\$password,', re.M)
    source, replacements = connection.subn(
        lambda match: match.group(1) + 'DBI->connect($ENV{"MAIN_DBI_DSN"},$user,$password, '
        + '# satvvik: Use the isolated import database and configured connection. ', source)
    if replacements != 1:
        raise RefreshError('Cannot isolate the legacy Perl connection: ' + str(script))
    declaration = re.compile(r'(^[ \t]*my\s*\(\s*\$db,\s*\$user,\s*\$password\s*\)\s*;)', re.M)
    source, replacements = declaration.subn(
        lambda match: match.group(0) + '\n$password = $ENV{"DB_PASS"}; # satvvik: Read the password without exposing it in argv.', source)
    if replacements != 1:
        raise RefreshError('Cannot isolate the legacy Perl credentials: ' + str(script))
    source = source.replace('if(!$password)', 'if(!defined $password)')
    destination = directory / Path(script).name
    destination.write_text(source)
    destination.chmod(0o600)
    helper = Path(script).with_name('Update.pm')
    if helper.is_file():
        shutil.copyfile(helper, directory / 'Update.pm')
    return destination


def run_stage(stage, root, job, reference, inputs, connection, conn):
    name, relative, input_name, clear_tables = stage
    if conn.database != reference:
        raise RefreshError('Refusing to clear tables outside the isolated import database')
    # satvvik: Restart a failed stage by clearing only its owned staging tables.
    cursor = conn.cursor()
    try:
        for table in clear_tables:
            cursor.execute('TRUNCATE TABLE ' + qualified(reference, table))
    finally:
        cursor.close()
    conn.commit()
    directory = Path(job) / 'adapters' / name
    directory.mkdir(parents=True, exist_ok=True)
    script = Path(root) / 'scripts' / relative
    env = os.environ.copy()
    env.update(DB_HOST=connection['host'], DB_PORT=str(connection['port']), DB_USER=connection['user'],
               DB_PASS=connection['password'], DB_SOCKET=connection.get('socket') or '',
               MAIN_REFERENCE_DB=reference, PYTHONDONTWRITEBYTECODE='1', UPDATE_EMAIL_NOTICES='0')
    if connection.get('socket'):
        dsn = 'dbi:mysql:database=' + reference + ';mysql_socket=' + connection['socket']
    else:
        host = '127.0.0.1' if connection['host'] == 'localhost' else connection['host']
        dsn = 'dbi:mysql:database=' + reference + ';host=' + host + ';port=' + str(connection['port'])
    env['MAIN_DBI_DSN'] = dsn
    if script.suffix == '.pl':
        command = ['perl', str(perl_adapter(script, directory, reference))]
    else:
        python_adapter(directory)
        env['PYTHONPATH'] = str(directory) + os.pathsep + env.get('PYTHONPATH', '')
        command = [sys.executable, str(script)]
    if input_name:
        if name == 'fda':
            command += ['-f', inputs[input_name]]
        elif name == 'drugbank':
            # satvvik: The legacy loader runs grep through a shell, so give it a fixed local filename.
            local_input = directory / 'full_database.xml'
            local_input.unlink(missing_ok=True)
            local_input.symlink_to(inputs[input_name])
            command.append(local_input.name)
        else:
            command.append(inputs[input_name])
    command += ['-d', reference, '-u', connection['user']]
    log = Path(job) / (name + '.log')
    LOG.info('Updating %s using the original loader', name)
    with log.open('w') as output:
        process = subprocess.Popen(command, cwd=directory, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            while True:
                try:
                    status = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    LOG.info('%s is still running; loader output: %s', name, log)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    # satvvik: Some legacy loaders print errors but exit successfully; treat that as stage failure.
    error = False
    with log.open(errors='replace') as output:
        for line in output:
            if re.match(r'^(Error:|Error encountered:|Unexpected error:)', line):
                error = True
                break
    if status or error:
        raise RefreshError(name + ' failed; the original loader output is in ' + str(log))
    conn.commit()
