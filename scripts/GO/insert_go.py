#!/usr/bin/env python

'''
sykim's code
'''

import sys
import MySQLdb

# $IMPORT PATH%
from myconfig import Config

def main(fname, conn):
    cursor = conn.cursor()

    with open(fname, 'r') as f:
        for line in f:
            cols = line.strip().split(' ')
            entrez_id = int(cols[0])
            go_id = cols[1]

            cursor.execute(
                'insert ignore into go_annotations (entrez_id, go_id) '
                'values (%s, %s)',
                (entrez_id, go_id)
            )

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print 'Usage: python insert.py <go_file>'
        sys.exit(1)
    fname = sys.argv[1]

    conf = Config().get('db')
    conn = MySQLdb.connect(
        host=conf['host'],
        db='wiki_pred',
        user=conf['username'],
        passwd=conf['password'],
    )

    try:
        main(fname, conn)
        conn.commit()
        print 'Done committing'
    except:
        print "Unexpected error:", sys.exc_info()[0]
        print 'Not committing'
        conn.rollback()
    finally:
        conn.close()

