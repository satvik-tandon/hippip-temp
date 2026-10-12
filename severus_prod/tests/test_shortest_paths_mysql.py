from contextlib import contextmanager
import importlib.util
import io
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import mysql.connector
import networkx as nx


sys.dont_write_bytecode = True
TARGET = Path(os.environ.get('SHORTEST_TEST_SCRIPT', '/data/Projects/Hippip/scripts/shortest_paths/update_db.py'))
sys.path.insert(0, str(TARGET.parent))
import update_db as update
SOCKET = os.environ['SHORTEST_TEST_SOCKET']
assert re.fullmatch(r'/tmp/hippip-shortest-mysql-[^/]+/mysql.sock', SOCKET), 'Only a disposable test socket is allowed'


class StopAfterBatch(update.ShortestPathJob):
    def commit_batch(self, rows, position):
        super().commit_batch(rows, position)
        raise RuntimeError('fixture interruption after a committed batch')


class FaultCursor:
    def __init__(self, proxy, cursor):
        self.proxy, self.cursor = proxy, cursor

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, query, *args, **kwargs):
        result = self.cursor.execute(query, *args, **kwargs)
        if self.proxy.enabled and self.proxy.match(query):
            self.proxy.enabled = False
            if self.proxy.mode == 'commit_ack':
                self.proxy.fail_commit = True
            else:
                raise RuntimeError('fixture injected database failure')
        return result

    def executemany(self, *args, **kwargs):
        return self.cursor.executemany(*args, **kwargs)


class FaultConnection:
    def __init__(self, conn, match, mode='execute'):
        self.conn, self.match, self.mode = conn, match, mode
        self.enabled = True
        self.fail_commit = False
        self.rollbacks = 0
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def cursor(self, *args, **kwargs):
        return FaultCursor(self, self.conn.cursor(*args, **kwargs))

    def commit(self):
        result = self.conn.commit()
        if self.fail_commit:
            self.fail_commit = False
            raise mysql.connector.OperationalError('fixture lost commit acknowledgement')
        return result

    def rollback(self):
        self.rollbacks += 1
        return self.conn.rollback()

    def close(self):
        self.closed = True
        return self.conn.close()


class ResumeTests(unittest.TestCase):
    sequence = 0

    def setUp(self):
        type(self).sequence += 1
        self.database = 'shortest_fixture_%d' % type(self).sequence
        self.admin = mysql.connector.connect(user='root', unix_socket=SOCKET, autocommit=True)
        cursor = self.admin.cursor()
        cursor.execute('CREATE DATABASE `%s`' % self.database)
        cursor.close()
        self.conn = self.connect()
        self.edges = [(4, 1), (1, 3), (3, 2), (2, 4), (8, 9), (8, 8)]
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('''CREATE TABLE valid_direct_interactions (
                entrez_id1 INT, entrez_id2 INT) ENGINE=InnoDB''')
            cursor.executemany('INSERT INTO valid_direct_interactions VALUES (%s,%s)', self.edges)
            cursor.execute('''CREATE TABLE shortest_paths (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                entrez_id1 INT, entrez_id2 INT, path_len INT,
                KEY entrez_id1(entrez_id1), KEY entrez_id2(entrez_id2)) ENGINE=InnoDB''')
            cursor.execute('INSERT INTO shortest_paths(entrez_id1,entrez_id2,path_len) VALUES (700,800,42)')
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.close()
        except mysql.connector.Error:
            pass
        cursor = self.admin.cursor()
        cursor.execute('DROP DATABASE `%s`' % self.database)
        cursor.close()
        self.admin.close()

    def connect(self):
        return mysql.connector.connect(user='root', unix_socket=SOCKET, database=self.database,
                                       autocommit=False, raise_on_warnings=True)

    def graph(self):
        with update.shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute('SELECT entrez_id1,entrez_id2 FROM valid_direct_interactions')
            graph = nx.Graph()
            graph.add_edges_from(update.canonical_shortest_edges(cursor.fetchall()))
        self.conn.commit()
        return graph

    def state(self):
        with update.shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute('SELECT * FROM hippip_shortest_path_state WHERE id=1')
            result = cursor.fetchone()
        self.conn.commit()
        return result

    def rows(self, table='shortest_paths'):
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('SELECT entrez_id1,entrez_id2,path_len FROM `%s` ORDER BY entrez_id1,entrez_id2' % table)
            rows = cursor.fetchall()
        self.conn.commit()
        return rows

    def expected(self):
        graph = self.graph()
        return sorted((left, right, distance)
                      for left, targets in nx.all_pairs_shortest_path_length(graph)
                      for right, distance in targets.items() if left < right)

    def run_job(self, job_type=update.ShortestPathJob, workers=1, batch=2, restart=False, conn=None):
        job = job_type(conn or self.conn, self.graph(), workers, batch)
        with update.shortest_database_lock(conn or self.conn):
            job.run(restart)
        return job

    def interrupt(self):
        with self.assertRaisesRegex(RuntimeError, 'interruption'):
            self.run_job(StopAfterBatch)
        self.conn.rollback()

    def test_complete_results_and_unique_pair_constraint(self):
        self.run_job()
        self.assertEqual(self.rows(), self.expected())
        self.assertEqual(self.state()['status'], 'completed')
        with update.shortest_cursor(self.conn) as cursor:
            with self.assertRaises(mysql.connector.IntegrityError):
                cursor.execute('INSERT INTO shortest_paths(entrez_id1,entrez_id2,path_len) VALUES (1,2,99)')
        self.conn.rollback()
        self.assertEqual(self.rows(), self.expected())

    def test_default_5000_batches_and_final_partial_batch(self):
        edges = list(nx.path_graph(110).edges())
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('DELETE FROM valid_direct_interactions')
            cursor.executemany('INSERT INTO valid_direct_interactions VALUES (%s,%s)', edges)
        self.conn.commit()
        sizes = []
        class Capture(update.ShortestPathJob):
            def commit_batch(inner, rows, position):
                sizes.append(len(rows))
                return super().commit_batch(rows, position)
        job = Capture(self.conn, self.graph(), workers=1)
        with update.shortest_database_lock(self.conn):
            job.run()
        self.assertEqual(sizes, [5000, 995])
        self.assertEqual(len(self.rows()), 5995)

    def test_resume_inside_source_with_changed_batch_size_and_workers(self):
        self.interrupt()
        before = self.state()
        self.assertEqual(before['written_rows'], 2)
        self.assertGreater(before['row_offset'], 0)
        self.assertEqual(len(self.rows(update.BUILD_TABLE)), 2)
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job(workers=2, batch=3)
        self.assertEqual(self.rows(), self.expected())
        self.assertEqual(self.state()['job_token'], before['job_token'])

    def test_checkpoint_failure_rolls_back_inserted_batch(self):
        proxy = FaultConnection(self.conn, lambda sql: 'SET source_index=' in sql)
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.run_job(conn=proxy)
        self.assertGreater(proxy.rollbacks, 0)
        self.assertEqual(self.state()['written_rows'], 0)
        self.assertEqual(self.rows(update.BUILD_TABLE), [])
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job()
        self.assertEqual(self.rows(), self.expected())

    def test_commit_ack_failure_resumes_without_replaying_rows(self):
        proxy = FaultConnection(self.conn, lambda sql: 'SET source_index=' in sql, mode='commit_ack')
        with self.assertRaises(mysql.connector.OperationalError):
            self.run_job(conn=proxy)
        self.assertEqual(self.state()['written_rows'], 2)
        self.assertEqual(len(self.rows(update.BUILD_TABLE)), 2)
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job()
        self.assertEqual(self.rows(), self.expected())

    def test_batch_insert_duplicate_rolls_back(self):
        self.interrupt()
        state = self.state()
        job = update.ShortestPathJob(self.conn, self.graph(), workers=1, batch_size=2)
        job.state = state
        duplicate = self.rows(update.BUILD_TABLE)[0]
        with self.assertRaises(mysql.connector.IntegrityError):
            job.commit_batch([(2, 9, 5), duplicate], (state['source_index'], state['row_offset'] + 2))
        self.assertEqual(self.state()['written_rows'], 2)
        self.assertEqual(len(self.rows(update.BUILD_TABLE)), 2)

    def test_existing_results_remain_until_complete_publication(self):
        observations = []
        outer = self
        class Observe(update.ShortestPathJob):
            def commit_batch(inner, rows, position):
                super().commit_batch(rows, position)
                observations.append(outer.rows())
        self.run_job(Observe)
        self.assertTrue(observations)
        self.assertTrue(all(rows == [(700, 800, 42)] for rows in observations))
        self.assertEqual(self.rows(), self.expected())

    def test_interruption_before_table_swap_resumes_ready_build(self):
        class BeforeSwap(update.ShortestPathJob):
            def finish_publication(inner):
                raise RuntimeError('fixture before swap')
        with self.assertRaisesRegex(RuntimeError, 'before swap'):
            self.run_job(BeforeSwap)
        self.assertEqual(self.state()['status'], 'ready')
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job()
        self.assertEqual(self.rows(), self.expected())

    def test_crash_after_atomic_swap_recovers_marker(self):
        proxy = FaultConnection(self.conn, lambda sql: sql.startswith('RENAME TABLE'))
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.run_job(conn=proxy)
        state = self.state()
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(self.rows(), self.expected())
        self.run_job()
        self.assertEqual(self.state()['status'], 'completed')
        self.assertEqual(self.state()['job_token'], state['job_token'])
        self.assertEqual(self.rows(), self.expected())

    def test_initialization_failure_before_create_recovers(self):
        proxy = FaultConnection(self.conn, lambda sql: sql.startswith('INSERT INTO `hippip_shortest_path_state`'), mode='commit_ack')
        with self.assertRaises(mysql.connector.OperationalError):
            self.run_job(conn=proxy)
        self.assertEqual(self.state()['status'], 'initializing')
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job()
        self.assertEqual(self.rows(), self.expected())

    def test_initialization_failure_after_create_recovers(self):
        proxy = FaultConnection(self.conn, lambda sql: sql.startswith('CREATE TABLE `hippip_shortest_paths_build` LIKE'))
        with self.assertRaises(RuntimeError):
            self.run_job(conn=proxy)
        self.assertEqual(self.state()['status'], 'initializing')
        self.run_job()
        self.assertEqual(self.rows(), self.expected())

    def test_graph_change_blocks_resume_and_restart_only_replaces_staging(self):
        self.interrupt()
        state = self.state()
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('INSERT INTO valid_direct_interactions VALUES (4,8)')
        self.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'differs from the checkpoint'):
            self.run_job()
        self.assertEqual(self.state()['job_token'], state['job_token'])
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.run_job(restart=True)
        self.assertNotEqual(self.state()['job_token'], state['job_token'])
        self.assertEqual(self.rows(), self.expected())

    def test_graph_change_during_build_blocks_publication(self):
        class ChangeGraph(update.ShortestPathJob):
            def build(inner):
                super().build()
                with update.shortest_cursor(inner.conn) as cursor:
                    cursor.execute('INSERT INTO valid_direct_interactions VALUES (4,8)')
                inner.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'changed during computation'):
            self.run_job(ChangeGraph)
        self.assertEqual(self.rows(), [(700, 800, 42)])
        self.assertEqual(self.state()['status'], 'ready')

    def test_completed_unchanged_rerun_does_not_append_or_recompute(self):
        self.run_job()
        token = self.state()['job_token']
        before = self.rows()
        with patch.object(update, 'shortest_source_results', side_effect=AssertionError('Must not recompute')):
            self.run_job()
        self.assertEqual(self.state()['job_token'], token)
        self.assertEqual(self.rows(), before)

    def test_new_graph_after_completion_starts_new_rebuild(self):
        self.run_job()
        token = self.state()['job_token']
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('INSERT INTO valid_direct_interactions VALUES (4,8)')
        self.conn.commit()
        self.run_job()
        self.assertNotEqual(self.state()['job_token'], token)
        self.assertEqual(self.rows(), self.expected())

    def test_deleted_published_rows_require_restart(self):
        self.run_job()
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('DELETE FROM shortest_paths LIMIT 1')
        self.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'Published rows differ'):
            self.run_job()
        self.run_job(restart=True)
        self.assertEqual(self.rows(), self.expected())

    def test_empty_graph_publishes_valid_empty_result(self):
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('DELETE FROM valid_direct_interactions')
        self.conn.commit()
        self.run_job(workers=6)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.state()['written_rows'], 0)
        self.run_job()

    def test_six_workers_match_single_worker_and_networkx(self):
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('INSERT INTO valid_direct_interactions VALUES (10,11),(11,12),(12,13),(13,14),(14,15),(15,16)')
        self.conn.commit()
        self.run_job(workers=6, batch=5)
        self.assertEqual(self.rows(), self.expected())

    def test_concurrent_job_lock_is_rejected(self):
        other = self.connect()
        try:
            with update.shortest_database_lock(self.conn):
                with self.assertRaisesRegex(update.ShortestPathError, 'already running'):
                    with update.shortest_database_lock(other):
                        self.fail('Concurrent lock must not be acquired')
        finally:
            other.close()
        with update.shortest_database_lock(self.conn):
            pass

    def test_tampered_staging_count_blocks_resume(self):
        self.interrupt()
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('DELETE FROM hippip_shortest_paths_build LIMIT 1')
        self.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'Staging rows differ'):
            self.run_job()
        self.assertEqual(self.rows(), [(700, 800, 42)])

    def test_equivalent_reordered_edges_resume_the_same_worklist(self):
        self.interrupt()
        state = self.state()
        reordered = [(right, left) for left, right in reversed(self.edges)]
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('DELETE FROM valid_direct_interactions')
            cursor.executemany('INSERT INTO valid_direct_interactions VALUES (%s,%s)', reordered)
        self.conn.commit()
        self.run_job(batch=3)
        self.assertEqual(self.state()['job_token'], state['job_token'])
        self.assertEqual(self.rows(), self.expected())

    def test_final_publication_lock_blocks_graph_writes(self):
        job = update.ShortestPathJob(self.conn, self.graph(), workers=1, batch_size=2)
        job.validate_target()
        job.create_state_table()
        job.start_new()
        begun, finished = threading.Event(), threading.Event()
        errors = []
        def writer():
            conn = self.connect()
            try:
                with update.shortest_cursor(conn) as cursor:
                    begun.set()
                    cursor.execute('INSERT INTO valid_direct_interactions VALUES (4,8)')
                conn.commit()
            except BaseException as exc:
                errors.append(exc)
            finally:
                conn.close()
                finished.set()
        thread = threading.Thread(target=writer)
        with update.shortest_publication_lock(self.conn):
            thread.start()
            self.assertTrue(begun.wait(5))
            self.assertFalse(finished.wait(0.15))
            self.assertEqual(update.current_shortest_graph_identity(self.conn, commit=False), job.fingerprint)
        thread.join(5)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        self.assertNotEqual(update.current_shortest_graph_identity(self.conn), job.fingerprint)

    def test_foreign_staging_table_is_not_deleted(self):
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('CREATE TABLE hippip_shortest_paths_build (id INT) ENGINE=InnoDB')
            cursor.execute('INSERT INTO hippip_shortest_paths_build VALUES (123)')
        self.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'no job marker'):
            self.run_job()
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('SELECT id FROM hippip_shortest_paths_build')
            self.assertEqual(cursor.fetchall(), [(123,)])

    def test_main_failure_rolls_back_and_closes_connection(self):
        proxy = FaultConnection(self.conn, lambda sql: 'SET source_index=' in sql)
        argv = ['update_db.py', '-d', self.database, '-u', 'root', '-p', '', '--workers', '1', '--batch-size', '2']
        with patch.object(sys, 'argv', argv), patch.object(update.mysql.connector, 'connect', return_value=proxy):
            self.assertEqual(update.main(), 1)
        self.assertTrue(proxy.closed)
        self.assertGreater(proxy.rollbacks, 0)
        self.conn = self.connect()
        self.assertEqual(self.state()['written_rows'], 0)
        self.assertEqual(self.rows(update.BUILD_TABLE), [])
        self.assertEqual(self.rows(), [(700, 800, 42)])

    def test_actual_executable_defaults_to_six_and_can_rerun(self):
        env = dict(os.environ, PRODUCTION_DB=self.database, DB_USER='root', DB_PASS='', DB_SOCKET=SOCKET,
                   DB_HOST='localhost', DB_PORT='3306', PYTHONDONTWRITEBYTECODE='1')
        env.pop('SHORTEST_PATH_WORKERS', None)
        env.pop('SHORTEST_PATH_RESTART', None)
        for attempt in range(2):
            result = subprocess.run([sys.executable, '-B', str(TARGET)], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            if attempt == 0:
                self.assertIn('6 workers, batches of 5000', result.stderr)
            else:
                self.assertIn('already complete', result.stderr)
        self.assertEqual(self.rows(), self.expected())

    def test_invalid_cli_settings_do_not_connect(self):
        for args in (['--workers', '7'], ['--batch-size', '0']):
            with patch.object(sys, 'argv', ['update_db.py'] + args), \
                 patch.object(update.mysql.connector, 'connect') as connect, \
                 patch.object(sys, 'stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    update.main()
                self.assertEqual(result.exception.code, 2)
                connect.assert_not_called()

    def test_nontransactional_target_is_rejected_before_rebuild(self):
        with update.shortest_cursor(self.conn) as cursor:
            cursor.execute('ALTER TABLE shortest_paths ENGINE=MyISAM')
        self.conn.commit()
        with self.assertRaisesRegex(update.ShortestPathError, 'InnoDB'):
            self.run_job()
        self.assertEqual(self.rows(), [(700, 800, 42)])

    def test_original_bfs_on_random_graphs(self):
        for seed in range(20):
            graph = nx.gnp_random_graph(20, 0.15, seed=seed)
            rows = [row for source in graph for row in update.shortest_path_worker(source, graph)]
            expected = {(left, right, distance)
                        for left, targets in nx.all_pairs_shortest_path_length(graph)
                        for right, distance in targets.items() if left < right}
            self.assertEqual(set(rows), expected)
            self.assertEqual(len(rows), len(set(rows)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
