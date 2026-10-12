#!/home/bin/python

import MySQLdb
import sys
import pdb

from obo import Parser
from optparse import OptionParser

def main(fname, conn):
    cursor = conn.cursor()
    parser = Parser(fname)

    for stanza in parser:
        try:
            category = str(stanza.tags['namespace'][0])
        except:
            continue

        if category.endswith('process'):
            c = 'Process'
        elif category.endswith('component'):
            c = 'Component'
        elif category.endswith('function'):
            c = 'Function'
        else:
            continue

        term_id   = str(stanza.tags['id'][0])
        term_name = str(stanza.tags['name'][0])

        cursor.execute(
            'insert ignore into go_terms (id, name, category) '
            'values (%s, %s, %s)',
            (term_id, term_name, c)
        )
    cursor.close()
    return

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user")
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db")

    (options, args) = parser.parse_args()

    if len(args) != 1:
        print 'Usage: python insert_go_terms.py /path/to/gene_ontology_ext.obo'
        sys.exit(1)

    fname = args[0]

    db = None
    user = None
    passwd = None

    if options.db:
        db = options.db
    else:
        print 'MySQL database: ',
        db = sys.stdin.readline().rstrip()
    if options.user:
        user = options.user
    else:
        print 'MySQL username: ',
        user = sys.stdin.readline().rstrip()
    if options.passwd:
        passwd = options.passwd
    else:
        passwd = getpass.getpass('MySQL password: ')


    conn = MySQLdb.connect(
        host='localhost',
        db=db,
        user=user,
        passwd=passwd,
    )

    main(fname, conn)
    conn.commit()
    conn.close()
    print 'Done inserting'
