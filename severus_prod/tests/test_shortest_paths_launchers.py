import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
import tempfile


STUB = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
def flag(option):
    return args[args.index(option)+1] if option in args else None
def record(value):
    with Path(os.environ['MOCK_TRACE']).open('a') as handle:
        handle.write(json.dumps(value)+'\n')
if name=='mysql':
    record({'kind':'mysql','database':flag('-D'),'sql':flag('-e')})
    sys.exit(int(os.environ.get('MOCK_ACCESS_STATUS','0')))
if name=='sendmail':
    message=sys.stdin.read()
    record({'kind':'mail','subject':message.splitlines()[0] if message else ''})
    sys.exit(int(os.environ.get('MOCK_MAIL_STATUS','0')))
loader='shortest_paths/update_db.py'
record({'kind':'loader','loader':loader,'database':flag('-d'),'args':args,
        'password_in_environment':'DB_PASS' in os.environ,
        'workers_env':os.environ.get('SHORTEST_PATH_WORKERS'),
        'batch_env':os.environ.get('SHORTEST_PATH_BATCH_SIZE'),
        'restart_env':os.environ.get('SHORTEST_PATH_RESTART')})
if os.environ.get('MOCK_FAIL_LOADER')==loader:
    sys.exit(9)
'''
ROOT = Path(os.environ.get('SHORTEST_LAUNCHER_ROOT', str(Path(__file__).resolve().parents[1])))


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shortest-launcher-test-')
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        self.bin = self.base / 'bin'
        self.trace = self.base / 'trace.jsonl'
        for directory in (self.bin, self.project/'scripts/shortest_paths'):
            directory.mkdir(parents=True)
        for path in (self.bin/'mysql', self.bin/'sendmail', self.project/'scripts/shortest_paths/update_db.py'):
            path.write_text(STUB)
            path.chmod(0o755)
        self.env=dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                      HIPPIP_ROOT=str(self.project), MOCK_TRACE=str(self.trace),
                      DB_USER='fixture_user', DB_PASS='fixture_password', UPDATE_EMAIL_NOTICES='0')
        self.env.pop('PRODUCTION_DB',None)
        for name in ('SHORTEST_PATH_WORKERS', 'SHORTEST_PATH_BATCH_SIZE', 'SHORTEST_PATH_RESTART'):
            self.env.pop(name, None)

    def tearDown(self):
        self.temp.cleanup()

    def run_stage(self, database, stage, args=(), extra=None):
        self.trace.unlink(missing_ok=True)
        env=self.env.copy()
        if extra:
            env.update(extra)
        result=subprocess.run(['bash',str(ROOT/database/stage),*args], env=env,
                              input='\n',text=True,capture_output=True,timeout=10)
        records=[json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []
        self.assertNotIn('fixture_password',result.stdout+result.stderr)
        return result,records

    def test_all_help_without_database_or_credentials(self):
        for database in ('db_pred', 'db_published', 'db_k_graph'):
            result, records = self.run_stage(database, '3_shortest-paths.sh', args=('--help',))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('6 workers', result.stdout)
            self.assertEqual(records, [])

    def test_no_truncate_and_password_only_in_environment(self):
        for database in ('db_pred', 'db_published'):
            result, records = self.run_stage(database, '3_shortest-paths.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([record['sql'] for record in records if record['kind'] == 'mysql'], [';'])
            loaders = [record for record in records if record['kind'] == 'loader']
            self.assertEqual(len(loaders), 1)
            self.assertNotIn('-p', loaders[0]['args'])
            self.assertTrue(loaders[0]['password_in_environment'])
            self.assertEqual(loaders[0]['database'], database)
            self.assertIn('Updated shortest paths in ' + database, result.stdout)

    def test_flags_and_environment_are_forwarded(self):
        arguments = ('--workers', '6', '--batch-size', '5000', '--restart')
        result, records = self.run_stage('db_pred', '3_shortest-paths.sh', args=arguments,
                                        extra={'SHORTEST_PATH_WORKERS': '5', 'SHORTEST_PATH_BATCH_SIZE': '1000',
                                               'SHORTEST_PATH_RESTART': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        loader = records[-1]
        self.assertEqual(loader['args'][-5:], list(arguments))
        self.assertEqual([loader['workers_env'], loader['batch_env'], loader['restart_env']], ['5', '1000', '1'])

    def test_bad_arguments_before_any_database_operation(self):
        for database in ('db_pred', 'db_published', 'db_k_graph'):
            for arguments in (('--bad-option',), ('--batch-size',)):
                result, records = self.run_stage(database, '3_shortest-paths.sh', args=arguments)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(records, [])

    def test_worker_failure_not_reexecuted_or_reported_as_success(self):
        result, records = self.run_stage('db_pred', '3_shortest-paths.sh', extra={'MOCK_FAIL_LOADER': 'shortest_paths/update_db.py'})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(sum(record.get('loader') == 'shortest_paths/update_db.py' for record in records), 1)
        self.assertIn('Failed to update shortest paths', result.stderr)
        self.assertNotIn('Updated shortest paths in ', result.stdout)

    def test_access_failure_does_not_start_calculator(self):
        result, records = self.run_stage('db_published', '3_shortest-paths.sh', extra={'MOCK_ACCESS_STATUS': '4'})
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(record['kind'] == 'loader' for record in records))
        self.assertIn('Unable to access database', result.stderr)

    def test_notification_failure_does_not_change_success(self):
        result, records = self.run_stage('db_pred', '3_shortest-paths.sh', extra={'UPDATE_EMAIL_NOTICES': '1', 'MOCK_MAIL_STATUS': '5'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Could not send success notification', result.stderr)

    def test_kgraph_preserves_prompts_and_messages_without_truncate(self):
        # Keep its original production root unchanged; isolate a copy for this test.
        source = ROOT / 'db_k_graph/3_shortest-paths.sh'
        target = self.base / 'kgraph.sh'
        target.write_text(source.read_text().replace('ROOT_DIR="/data/Projects/Hippip"', 'ROOT_DIR="${HIPPIP_ROOT}"'))
        result = subprocess.run(['bash', str(target), '--workers=6', '--batch-size=5000'], env=self.env,
                                input='fixture\nfixture_user\nfixture_password\n', capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('fixture_password', result.stdout + result.stderr)
        records = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertEqual([record['sql'] for record in records if record['kind'] == 'mysql'], [';'])
        loader = next(record for record in records if record['kind'] == 'loader')
        self.assertEqual(loader['database'], 'fixture')
        self.assertEqual(loader['args'][-2:], ['--workers=6', '--batch-size=5000'])
        self.assertNotIn('-p', loader['args'])
        self.assertIn('Updated shortest path', result.stdout)


if __name__ == '__main__':
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('LauncherTests.' + name, module=__import__(__name__))
                              for name in LauncherTests.__dict__ if name.startswith('test_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
