#!/usr/bin/python3

import networkx as nx
import getpass
import sys
import networkx as nx
import mysql.connector
from optparse import OptionParser
import os


def main():
    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user")
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db")
    parser.add_option("-w", "--workers", dest="workers", type="int",
                      default=os.environ.get("SHORTEST_PATH_WORKERS", "4"),
                      help="Source-gene workers (1-4; default: 4 or SHORTEST_PATH_WORKERS)")

    (options, args) = parser.parse_args()
    if not 1 <= options.workers <= 4:
        parser.error("workers must be an integer from 1 to 4")

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
    if options.passwd:
        passwd = options.passwd
    else:
        passwd = getpass.getpass('MySQL password: ')

    conn = mysql.connector.connect(
        host='localhost',
        db=db,
        user=user,
        passwd=passwd,
    )
    #conn.autocommit(True)

    #cursor = conn.cursor()
    cursor = conn.cursor(dictionary=True);

    G = nx.Graph()
    cursor.execute('SELECT entrez_id1, entrez_id2 FROM valid_direct_interactions')
    G.add_edges_from([(r.get('entrez_id1'),r.get('entrez_id2')) for r in cursor.fetchall()])

    for source, v, level in shortest_path_rows(G, options.workers):
        cursor.execute('INSERT IGNORE INTO shortest_paths (entrez_id1, entrez_id2, path_len) VALUES (%d, %d, %d)' % (source,v,level))
        conn.commit()
    cursor.close()
    conn.close()


# Added workers: the original BFS runs independently for each source gene.
# Only the parent process performs the original inserts and per-row commits.
# A bounded queue preserves source order without retaining the whole result set.
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


if __name__ == '__main__':
    main()
