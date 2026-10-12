import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time

import mysql.connector


binary = shutil.which('mysqld')
if not binary:
    raise SystemExit('mysqld is required')
with tempfile.TemporaryDirectory(prefix='hippip-publication-citation-mysql-') as temporary:
    root = Path(temporary)
    data = root / 'data'
    data.mkdir()
    temporary_files = root / 'tmp'
    temporary_files.mkdir()
    user = pwd.getpwuid(os.geteuid()).pw_name
    base = [binary, '--no-defaults', '--user=' + user, '--datadir=' + str(data),
            '--tmpdir=' + str(temporary_files), '--mysqlx=0']
    initialize = subprocess.run(base + ['--initialize-insecure'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=60)
    if initialize.returncode:
        print(initialize.stdout)
        raise SystemExit(initialize.returncode)
    with (root / 'stdout.log').open('w') as output:
        process = subprocess.Popen(base + ['--skip-networking', '--socket=' + str(root / 'mysql.sock'),
                                   '--pid-file=' + str(root / 'mysqld.pid'), '--log-error=' + str(root / 'server.log'),
                                   '--innodb-buffer-pool-size=64M'], stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    conn = mysql.connector.connect(user='root', unix_socket=str(root / 'mysql.sock'), connection_timeout=1)
                    conn.close()
                    break
                except mysql.connector.Error:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        print((root / 'server.log').read_text() if (root / 'server.log').exists() else 'Server did not start')
                        raise SystemExit('Disposable MySQL server failed to start')
                    time.sleep(0.1)
            env = dict(os.environ, PUBLICATION_TEST_SOCKET=str(root / 'mysql.sock'), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('test_publication_citations_mysql.py'))], env=env)
            raise SystemExit(result.returncode)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
