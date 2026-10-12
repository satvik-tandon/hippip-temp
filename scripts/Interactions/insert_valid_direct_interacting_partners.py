#!/usr/bin/python

"""Usage:
    python insert_valid_direct_interacting_partners.py

(Deletes) and inserts into the valid_direct_interacting_partners table
"""

import sys
import getpass
#import MySQLdb
import mysql.connector
from optparse import OptionParser

def get_edges(cursor):
    query = '''select id, entrez_id1, entrez_id2, known, predicted
               from valid_direct_interactions'''
    cursor.execute(query)
    for _, eid1, eid2, known, predicted in cursor.fetchall():
        yield eid1, eid2, known, predicted


def main(conn):
    cursor = conn.cursor()
    cursor.execute('truncate table valid_direct_interacting_partners')

    for eid1, eid2, known, predicted in get_edges(cursor):
        if eid1 == eid2:
            continue
        cursor.execute(
            '''insert ignore into valid_direct_interacting_partners
            (entrez_id1, entrez_id2, known, predicted)
            values (%s, %s, %s, %s)''',
            (eid1, eid2, known, predicted)
        )
        cursor.execute(
            '''insert ignore into valid_direct_interacting_partners
            (entrez_id1, entrez_id2, known, predicted)
            values (%s, %s, %s, %s)''',
            (eid2, eid1, known, predicted)
        )


if __name__ == '__main__':
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
        print('MySQL database: ', end='')
        db = input().strip()
    if options.user:
        user = options.user
    else:
        print('MySQL username: ', end='')
        user = input().strip()
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

    exit_val = 0
    try:
        main(conn)
        conn.commit()
        print('Done committing')
    except:
        print("Unexpected error:", sys.exc_info()[0])
        print("Not committing")
        conn.rollback()
        exit_val = 1
    finally:
        conn.close()
    sys.exit(exit_val)
