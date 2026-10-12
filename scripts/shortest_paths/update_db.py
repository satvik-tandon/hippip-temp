#!/usr/bin/python3

import networkx as nx
import getpass
import sys
import networkx as nx
import mysql.connector
from optparse import OptionParser
import os
import hashlib
import logging
import re
import uuid
from contextlib import contextmanager


def main():
    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user", default=os.environ.get("DB_USER"))
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db", default=os.environ.get("PRODUCTION_DB"))
    parser.add_option("-w", "--workers", dest="workers", type="int",
                      default=os.environ.get("SHORTEST_PATH_WORKERS", "6"),
                      help="Source-gene workers (1-6; default: 6 or SHORTEST_PATH_WORKERS)")
    parser.add_option("--batch-size", dest="batch_size", type="int",
                      default=os.environ.get("SHORTEST_PATH_BATCH_SIZE", "5000"),
                      help="Paths per transaction (default: 5000 or SHORTEST_PATH_BATCH_SIZE)")
    parser.add_option("--restart", action="store_true", default=os.environ.get("SHORTEST_PATH_RESTART", "0") == "1",
                      help="Discard unfinished staging work and rebuild; published results are preserved")
    parser.add_option("--host", default=os.environ.get("DB_HOST", "localhost"))
    parser.add_option("--port", type="int", default=os.environ.get("DB_PORT", "3306"))
    parser.add_option("--socket", dest="socket", default=os.environ.get("DB_SOCKET"))

    (options, args) = parser.parse_args()
    if not 1 <= options.workers <= 6:
        parser.error("workers must be an integer from 1 to 6")
    if not 1 <= options.batch_size <= 50000:
        parser.error("batch size must be an integer from 1 to 50000")
    if os.environ.get("SHORTEST_PATH_RESTART", "0") not in ("0", "1"):
        parser.error("SHORTEST_PATH_RESTART must be 0 or 1")

    if len(args) != 0:
        sys.stderr.write('%s\n' % __doc__)
        sys.exit(1)

    db = None
    user = None
    passwd = None
    if options.db:
        db = options.db
    else:
        # print 'MySQL dbname: ',
        # db = sys.stdin.readline().rstrip()
        db = input('MySQL dbname: ').strip()
    if options.user:
        user = options.user
    else:
        # print 'MySQL username: ',
        # user = sys.stdin.readline().rstrip()
        user = input('MySQL username: ').strip()
    if options.passwd is not None:
        passwd = options.passwd
    elif "DB_PASS" in os.environ:
        passwd = os.environ["DB_PASS"]
    else:
        passwd = getpass.getpass('MySQL password: ')

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = None
    cursor = None
    try:
        connection_args = dict(host=options.host, port=options.port, db=db, user=user, passwd=passwd,
                               autocommit=False, connection_timeout=15, raise_on_warnings=True)
        if options.socket:
            connection_args["unix_socket"] = options.socket
        conn = mysql.connector.connect(**connection_args)
        #conn.autocommit(True)

        with shortest_database_lock(conn):
            #cursor = conn.cursor()
            cursor = conn.cursor(dictionary=True);

            G = nx.Graph()
            cursor.execute('SELECT entrez_id1, entrez_id2 FROM valid_direct_interactions')
            G.add_edges_from(canonical_shortest_edges(cursor.fetchall()))
            cursor.close()
            cursor = None
            conn.commit()
            ShortestPathJob(conn, G, options.workers, options.batch_size).run(options.restart)
        return 0
    except KeyboardInterrupt:
        LOG.warning("Interrupted; committed staging batches are saved. Rerun to resume.")
        return 130
    except Exception as exc:
        message = str(exc).replace(passwd, "[redacted]") if passwd else str(exc)
        LOG.error("FAILED: %s. Committed progress is saved; published results are preserved until a complete swap.", message)
        return 1
    finally:
        if conn is not None:
            rollback_shortest_transaction(conn)
            if cursor is not None:
                try:
                    cursor.close()
                except mysql.connector.Error:
                    LOG.warning("Could not close the input cursor cleanly")
            try:
                conn.close()
            except mysql.connector.Error:
                LOG.warning("Could not close the database connection cleanly")


# Retained worker notes from before batching; current commits are per batch.
# Added workers: the original BFS runs independently for each source gene.
# Only the parent process performs the original inserts and per-row commits.
# A bounded queue preserves source order without retaining the whole result set.
# Batch/resume support below now commits paths and checkpoints together.
_WORKER_GRAPH = None


def initialize_shortest_path_worker(graph):
    global _WORKER_GRAPH
    _WORKER_GRAPH = graph


def shortest_path_worker(source, graph=None):
    G = _WORKER_GRAPH if graph is None else graph
    rows = []
    # Adapted from NetworkX source
    seen={}               # level (number of hops) when seen in BFS
    level=0               # the current level
    # sys.stdout.write ('%d %s\n' % (level, source))
    # sys.stdout.flush()
    nextlevel={source:1}  # dict of nodes to check at next level
    while nextlevel:
        thislevel=nextlevel  # advance to next level
        nextlevel={}         # and start a new list (fringe)
        for v in thislevel:
            if v not in seen:
                seen[v]=True # set the level of vertex v
                nextlevel.update(G[v]) # add neighbors of v
                if source < v:
                    rows.append((source, v, level))
        level=level+1
    return rows


def shortest_path_rows(graph, workers):
    from collections import deque
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    if not graph:
        return
    sources = iter(graph.nodes())
    if workers == 1:
        for source in sources:
            yield from shortest_path_worker(source, graph)
        return

    # Spawn workers with the graph only; database connections stay in the parent.
    with ProcessPoolExecutor(max_workers=min(workers, len(graph)),
                             mp_context=get_context("spawn"),
                             initializer=initialize_shortest_path_worker,
                             initargs=(graph,)) as executor:
        pending = deque()
        exhausted = False
        try:
            while not exhausted or pending:
                while not exhausted and len(pending) < workers:
                    try:
                        source = next(sources)
                    except StopIteration:
                        exhausted = True
                    else:
                        pending.append(executor.submit(shortest_path_worker, source))
                if pending:
                    # Preserve the original source, traversal and write order.
                    yield from pending.popleft().result()
        finally:
            for future in pending:
                future.cancel()


# Added batch/resume support. The original BFS worker above is unchanged.
# A unique pair key protects staging rows. Progress and data share one commit.
# Published results stay available until a complete build is swapped into place.
LOG = logging.getLogger("shortest_paths")
STATE_TABLE = "hippip_shortest_path_state"
BUILD_TABLE = "hippip_shortest_paths_build"
TABLE_MARKER = "hippip-shortest-paths-v1:"
ALGORITHM_VERSION = 1


class ShortestPathError(Exception):
    pass


@contextmanager
def shortest_cursor(conn, dictionary=False):
    cursor = conn.cursor(dictionary=dictionary)
    try:
        yield cursor
    finally:
        try:
            cursor.close()
        except mysql.connector.Error:
            LOG.warning("Could not close a database cursor cleanly")


def rollback_shortest_transaction(conn):
    try:
        conn.rollback()
    except mysql.connector.Error:
        LOG.warning("Could not roll back the connection; rerun to inspect durable progress")


@contextmanager
def shortest_database_lock(conn):
    with shortest_cursor(conn) as cursor:
        cursor.execute("SELECT DATABASE()")
        database = cursor.fetchone()[0]
        name = "hippip_shortest_" + hashlib.sha256(database.encode()).hexdigest()[:32]
        cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))
        if cursor.fetchone()[0] != 1:
            raise ShortestPathError("Another shortest-path job is already running for this database")
    try:
        yield
    finally:
        try:
            with shortest_cursor(conn) as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
                cursor.fetchone()
        except mysql.connector.Error:
            LOG.warning("Could not release the job lock explicitly; closing the connection releases it")


def canonical_shortest_edges(rows):
    edges = set()
    for row in rows:
        left, right = row.get("entrez_id1"), row.get("entrez_id2")
        if (not isinstance(left, int) or not isinstance(right, int)
                or isinstance(left, bool) or isinstance(right, bool)
                or left < 0 or right < 0):
            raise ShortestPathError("The interaction graph contains a missing or invalid gene ID")
        edges.add((min(left, right), max(left, right)))
    return sorted(edges)


def shortest_graph_identity(graph):
    digest = hashlib.sha256()
    for left, right in sorted((min(left, right), max(left, right)) for left, right in graph.edges()):
        digest.update(("%d,%d\n" % (left, right)).encode("ascii"))
    return digest.hexdigest()


def current_shortest_graph_identity(conn, commit=True):
    # Start a fresh read transaction so a stale snapshot cannot pass the final check.
    if commit:
        conn.commit()
    with shortest_cursor(conn, dictionary=True) as cursor:
        cursor.execute('SELECT entrez_id1, entrez_id2 FROM valid_direct_interactions')
        graph = nx.Graph()
        graph.add_edges_from(canonical_shortest_edges(cursor.fetchall()))
    identity = shortest_graph_identity(graph)
    if commit:
        conn.commit()
    return identity


@contextmanager
def shortest_publication_lock(conn):
    # Keep the graph fixed between its final validation and the atomic swap.
    conn.commit()
    with shortest_cursor(conn) as cursor:
        cursor.execute("LOCK TABLES `valid_direct_interactions` READ, `shortest_paths` WRITE, `hippip_shortest_paths_build` WRITE")
    try:
        yield
    finally:
        with shortest_cursor(conn) as cursor:
            cursor.execute("UNLOCK TABLES")


def shortest_source_results(graph, sources, start_index, workers):
    from collections import deque
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    if start_index == len(sources):
        return
    if workers == 1:
        for index in range(start_index, len(sources)):
            yield index, shortest_path_worker(sources[index], graph)
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(sources) - start_index),
                             mp_context=get_context("spawn"),
                             initializer=initialize_shortest_path_worker,
                             initargs=(graph,)) as executor:
        pending = deque()
        submit_index = start_index
        try:
            while submit_index < len(sources) or pending:
                while submit_index < len(sources) and len(pending) < workers:
                    pending.append((submit_index, executor.submit(shortest_path_worker, sources[submit_index])))
                    submit_index += 1
                index, future = pending.popleft()
                yield index, future.result()
        finally:
            for _, future in pending:
                future.cancel()


class ShortestPathJob:
    def __init__(self, conn, graph, workers=6, batch_size=5000):
        self.conn, self.graph = conn, graph
        self.workers, self.batch_size = workers, batch_size
        self.sources = sorted(graph.nodes())
        self.fingerprint = shortest_graph_identity(graph)
        self.expected_rows = sum(len(component) * (len(component) - 1) // 2
                                 for component in nx.connected_components(graph))
        self.state = None

    def table_info(self, name):
        with shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute("""SELECT ENGINE, TABLE_COMMENT FROM information_schema.TABLES
                              WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s""", (name,))
            return cursor.fetchone()

    def validate_target(self):
        with shortest_cursor(self.conn) as cursor:
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
        match = re.match(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version)
        if not match or tuple(map(int, match.groups())) < (8, 0, 13) or "mariadb" in version.lower():
            raise ShortestPathError("Staged publication requires MySQL 8.0.13 or newer for crash-safe atomic table swaps")
        info = self.table_info("shortest_paths")
        if not info or str(info["ENGINE"]).lower() != "innodb":
            raise ShortestPathError("shortest_paths must exist and use InnoDB")
        with shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute("""SELECT COLUMN_NAME, EXTRA FROM information_schema.COLUMNS
                              WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='shortest_paths'""")
            columns = {row["COLUMN_NAME"]: row["EXTRA"] for row in cursor.fetchall()}
            if not {"id", "entrez_id1", "entrez_id2", "path_len"} <= set(columns) or "auto_increment" not in columns["id"]:
                raise ShortestPathError("shortest_paths must have its legacy auto-increment ID and gene/distance columns")
            cursor.execute("""SELECT COUNT(*) AS total FROM information_schema.KEY_COLUMN_USAGE
                              WHERE (REFERENCED_TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME='shortest_paths')
                                 OR (TABLE_SCHEMA=DATABASE() AND TABLE_NAME='shortest_paths'
                                     AND REFERENCED_TABLE_NAME IS NOT NULL)""")
            if cursor.fetchone()["total"]:
                raise ShortestPathError("Cannot safely swap shortest_paths while it participates in foreign keys")
            cursor.execute("""SELECT COUNT(*) AS total FROM information_schema.TRIGGERS
                              WHERE TRIGGER_SCHEMA=DATABASE() AND EVENT_OBJECT_TABLE='shortest_paths'""")
            if cursor.fetchone()["total"]:
                raise ShortestPathError("Cannot safely clone shortest_paths while it has triggers")
        self.conn.commit()

    def create_state_table(self):
        info = self.table_info(STATE_TABLE)
        if info and str(info["ENGINE"]).lower() != "innodb":
            raise ShortestPathError("The shortest-path progress table must use InnoDB")
        if info:
            return
        with shortest_cursor(self.conn) as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS `hippip_shortest_path_state` (
                id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
                version INT UNSIGNED NOT NULL,
                graph_hash CHAR(64) NOT NULL,
                job_token CHAR(32) NOT NULL,
                status VARCHAR(16) NOT NULL,
                node_count INT UNSIGNED NOT NULL,
                expected_rows BIGINT UNSIGNED NOT NULL,
                source_index INT UNSIGNED NOT NULL,
                row_offset INT UNSIGNED NOT NULL,
                written_rows BIGINT UNSIGNED NOT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB""")
        self.conn.commit()

    def load_state(self):
        with shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute("SELECT * FROM `hippip_shortest_path_state` WHERE id=1")
            self.state = cursor.fetchone()
        self.conn.commit()
        if not self.state:
            return
        state = self.state
        if (state["version"] != ALGORITHM_VERSION
                or state["status"] not in ("initializing", "building", "ready", "completed")
                or not re.fullmatch(r"[0-9a-f]{32}", state["job_token"])
                or not re.fullmatch(r"[0-9a-f]{64}", state["graph_hash"])
                or not 0 <= state["source_index"] <= state["node_count"]
                or not 0 <= state["written_rows"] <= state["expected_rows"]
                or state["row_offset"] < 0
                or (state["source_index"] == state["node_count"] and state["row_offset"] != 0)):
            raise ShortestPathError("Invalid or unsupported shortest-path progress record")
        if state["status"] in ("ready", "completed") and (
                state["source_index"] != state["node_count"] or state["row_offset"] != 0
                or state["written_rows"] != state["expected_rows"]):
            raise ShortestPathError("Completed progress does not account for all expected paths")

    def marker(self):
        return TABLE_MARKER + self.state["job_token"]

    def old_table(self):
        return "hippip_shortest_paths_old_" + self.state["job_token"]

    def is_published(self):
        info = self.table_info("shortest_paths")
        return bool(info and info["TABLE_COMMENT"] == self.marker())

    def set_status(self, status):
        try:
            with shortest_cursor(self.conn) as cursor:
                cursor.execute("UPDATE `hippip_shortest_path_state` SET status=%s WHERE id=1 AND job_token=%s",
                               (status, self.state["job_token"]))
            self.conn.commit()
        except BaseException:
            rollback_shortest_transaction(self.conn)
            raise
        self.state["status"] = status

    def start_new(self):
        info = self.table_info(BUILD_TABLE)
        if info and not str(info["TABLE_COMMENT"]).startswith(TABLE_MARKER):
            raise ShortestPathError("The reserved staging table has no job marker; it was not deleted")
        state = {"id": 1, "version": ALGORITHM_VERSION, "graph_hash": self.fingerprint,
                 "job_token": uuid.uuid4().hex, "status": "initializing", "node_count": len(self.sources),
                 "expected_rows": self.expected_rows, "source_index": 0, "row_offset": 0, "written_rows": 0}
        try:
            with shortest_cursor(self.conn) as cursor:
                cursor.execute("""INSERT INTO `hippip_shortest_path_state`
                    (id,version,graph_hash,job_token,status,node_count,expected_rows,source_index,row_offset,written_rows)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE version=%s,graph_hash=%s,job_token=%s,status=%s,node_count=%s,
                        expected_rows=%s,source_index=0,row_offset=0,written_rows=0""",
                    tuple(state[name] for name in ("id", "version", "graph_hash", "job_token", "status", "node_count",
                                                   "expected_rows", "source_index", "row_offset", "written_rows"))
                    + tuple(state[name] for name in ("version", "graph_hash", "job_token", "status", "node_count", "expected_rows")))
            self.conn.commit()
        except BaseException:
            rollback_shortest_transaction(self.conn)
            raise
        self.state = state
        self.initialize_build()

    def ensure_pair_key(self):
        with shortest_cursor(self.conn, dictionary=True) as cursor:
            cursor.execute("""SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, SUB_PART
                              FROM information_schema.STATISTICS
                              WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX""",
                           (BUILD_TABLE,))
            indexes = {}
            for row in cursor.fetchall():
                if row["NON_UNIQUE"] == 0 and row["SUB_PART"] is None:
                    indexes.setdefault(row["INDEX_NAME"], []).append(row["COLUMN_NAME"])
        if any(len(columns) == 2 and set(columns) == {"entrez_id1", "entrez_id2"} for columns in indexes.values()):
            return
        with shortest_cursor(self.conn) as cursor:
            cursor.execute("ALTER TABLE `hippip_shortest_paths_build` ADD UNIQUE KEY `hippip_shortest_pair` (`entrez_id1`,`entrez_id2`)")

    def initialize_build(self):
        # Initialization is durable before DDL, so interruption here can be restarted safely.
        exists = self.table_info(BUILD_TABLE)
        with shortest_cursor(self.conn) as cursor:
            if exists:
                cursor.execute("DROP TABLE `hippip_shortest_paths_build`")
            cursor.execute("CREATE TABLE `hippip_shortest_paths_build` LIKE `shortest_paths`")
            cursor.execute("ALTER TABLE `hippip_shortest_paths_build` AUTO_INCREMENT=1, COMMENT=%s", (self.marker(),))
        self.ensure_pair_key()
        self.set_status("building")
        LOG.info("Started staged rebuild: %d genes, %d paths, %d workers, batches of %d",
                 len(self.sources), self.expected_rows, self.workers, self.batch_size)

    def commit_batch(self, rows, position):
        state = self.state
        if state["written_rows"] + len(rows) > self.expected_rows:
            raise ShortestPathError("Computed more paths than the graph permits")
        try:
            with shortest_cursor(self.conn) as cursor:
                if rows:
                    cursor.executemany("""INSERT INTO `hippip_shortest_paths_build`
                        (entrez_id1,entrez_id2,path_len) VALUES (%s,%s,%s)""", rows)
                    if cursor.rowcount != len(rows):
                        raise ShortestPathError("The database did not insert the complete batch")
                cursor.execute("""UPDATE `hippip_shortest_path_state`
                    SET source_index=%s,row_offset=%s,written_rows=%s
                    WHERE id=1 AND job_token=%s AND status='building'
                      AND source_index=%s AND row_offset=%s AND written_rows=%s""",
                    (position[0], position[1], state["written_rows"] + len(rows), state["job_token"],
                     state["source_index"], state["row_offset"], state["written_rows"]))
                if cursor.rowcount != 1:
                    raise ShortestPathError("Progress changed unexpectedly; the batch was rolled back")
            self.conn.commit()
        except BaseException:
            rollback_shortest_transaction(self.conn)
            raise
        state.update(source_index=position[0], row_offset=position[1], written_rows=state["written_rows"] + len(rows))
        LOG.info("Committed %d/%d paths; source %d/%d, offset %d", state["written_rows"], self.expected_rows,
                 state["source_index"], len(self.sources), state["row_offset"])

    def build(self):
        state = self.state
        info = self.table_info(BUILD_TABLE)
        if not info or str(info["ENGINE"]).lower() != "innodb" or info["TABLE_COMMENT"] != self.marker():
            raise ShortestPathError("The saved staging table is missing or belongs to another run; use --restart")
        if state["node_count"] != len(self.sources) or state["expected_rows"] != self.expected_rows:
            raise ShortestPathError("Graph metadata does not match saved progress")
        self.ensure_pair_key()
        with shortest_cursor(self.conn) as cursor:
            cursor.execute("SELECT COUNT(*) FROM `hippip_shortest_paths_build`")
            if cursor.fetchone()[0] != state["written_rows"]:
                raise ShortestPathError("Staging rows differ from committed progress; use --restart to rebuild")
        self.conn.commit()
        LOG.info("Resuming at %d/%d committed paths", state["written_rows"], self.expected_rows)
        begin = state["source_index"]
        initial_offset = state["row_offset"]
        batch = []
        position = (begin, initial_offset)
        results = shortest_source_results(self.graph, self.sources, begin, self.workers)
        try:
            for index, rows in results:
                offset = initial_offset if index == begin else 0
                if offset and offset >= len(rows):
                    raise ShortestPathError("The saved row offset does not match its source gene")
                for row_index in range(offset, len(rows)):
                    row = rows[row_index]
                    if row[0] != self.sources[index] or not row[0] < row[1] or row[2] <= 0:
                        raise ShortestPathError("A worker returned an invalid shortest-path row")
                    batch.append(row)
                    position = (index + 1, 0) if row_index + 1 == len(rows) else (index, row_index + 1)
                    if len(batch) == self.batch_size:
                        self.commit_batch(batch, position)
                        batch = []
                position = (index + 1, 0)
            if batch or position != (state["source_index"], state["row_offset"]):
                self.commit_batch(batch, position)
        finally:
            results.close()
        if self.state["written_rows"] != self.expected_rows:
            raise ShortestPathError("The completed computation has an unexpected row count")
        self.set_status("ready")

    def cleanup_old(self):
        # This name is derived from the durable job token, never from user input.
        try:
            if not self.table_info(self.old_table()):
                return
            with shortest_cursor(self.conn) as cursor:
                cursor.execute("DROP TABLE `%s`" % self.old_table())
            self.conn.commit()
        except mysql.connector.Error:
            LOG.warning("Published results are complete; could not remove the previous table %s", self.old_table())
            rollback_shortest_transaction(self.conn)

    def finish_publication(self):
        if not self.is_published():
            info = self.table_info(BUILD_TABLE)
            if not info or info["TABLE_COMMENT"] != self.marker():
                raise ShortestPathError("The ready staging table is missing or has the wrong marker")
            with shortest_cursor(self.conn) as cursor:
                cursor.execute("SELECT COUNT(*) FROM `hippip_shortest_paths_build`")
                if cursor.fetchone()[0] != self.expected_rows:
                    raise ShortestPathError("Staging row count failed validation; published results were preserved")
            self.conn.commit()
            if self.table_info(self.old_table()):
                raise ShortestPathError("The reserved previous-table name already exists; publication stopped")
            with shortest_publication_lock(self.conn):
                if current_shortest_graph_identity(self.conn, commit=False) != self.fingerprint:
                    raise ShortestPathError("The interaction graph changed during computation; use --restart after the main stage finishes")
                with shortest_cursor(self.conn) as cursor:
                    cursor.execute("RENAME TABLE `shortest_paths` TO `%s`, `hippip_shortest_paths_build` TO `shortest_paths`" % self.old_table())
            self.conn.commit()
        # The table marker recovers a crash after RENAME but before this status update.
        self.set_status("completed")
        self.cleanup_old()
        LOG.info("Completed: %d unique shortest paths published", self.expected_rows)

    def run(self, restart=False):
        self.validate_target()
        self.create_state_table()
        self.load_state()
        if self.state:
            if self.state["status"] in ("ready", "completed") and self.is_published():
                with shortest_cursor(self.conn) as cursor:
                    cursor.execute("SELECT COUNT(*) FROM `shortest_paths`")
                    if cursor.fetchone()[0] != self.state["expected_rows"]:
                        if not restart:
                            raise ShortestPathError("Published rows differ from saved progress; use --restart to rebuild")
                self.set_status("completed")
                self.cleanup_old()
            if self.state["status"] == "completed":
                if not self.is_published():
                    if not restart:
                        raise ShortestPathError("Published-table marker changed; use --restart to rebuild")
                elif self.state["graph_hash"] == self.fingerprint and not restart:
                    LOG.info("Shortest paths already complete for the unchanged graph; no rows were appended")
                    return
            elif self.state["graph_hash"] != self.fingerprint and not restart:
                raise ShortestPathError("The interaction graph differs from the checkpoint; use --restart to replace only unfinished staging work")
        if restart or not self.state or self.state["status"] == "completed":
            self.start_new()
        elif self.state["status"] == "initializing":
            self.initialize_build()
        if self.state["status"] == "building":
            self.build()
        if self.state["status"] == "ready":
            self.finish_publication()


if __name__ == '__main__':
    sys.exit(main())
