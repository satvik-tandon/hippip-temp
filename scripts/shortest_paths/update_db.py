#!/usr/bin/python3

import networkx as nx
import getpass
import sys
import networkx as nx
import mysql.connector
from optparse import OptionParser

parser = OptionParser()
parser.add_option("-u", "--username", dest="user")
parser.add_option("-p", "--password", dest="passwd")
parser.add_option("-d", "--database", dest="db")

(options, args) = parser.parse_args()

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

# Adapted from NetworkX source
for source in G.nodes():
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
                    cursor.execute('INSERT IGNORE INTO shortest_paths (entrez_id1, entrez_id2, path_len) VALUES (%d, %d, %d)' % (source,v,level))
                    conn.commit()
        level=level+1
cursor.close()
conn.close()
