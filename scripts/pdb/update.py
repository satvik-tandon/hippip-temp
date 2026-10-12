#!/usr/bin/python3


"""Usage:
    python update.py HUMAN_9606_idmapping.dat
"""

import sys
import getpass
# import MySQLdb
import mysql.connector
from optparse import OptionParser

def main(fname, conn):
    cursor = conn.cursor()

    cursor.execute('SELECT EXISTS (SELECT * FROM entrez2uniprots)')
    if cursor.fetchall()[0][0] == 0:
        sys.stderr.write("Error: entrez2uniprots table is empty!\n")
        return

    with open(fname, 'r') as f:
        for line in f:
            uniprot_id, db_source, external_id = line.strip().split('\t')
            if db_source == "PDB":
                cursor.execute("""
                    INSERT IGNORE INTO entrez2pdbs (entrez_id, pdb_id)
                    SELECT entrez_id, "%s"
                    FROM entrez2uniprots
                    WHERE uniprot_id = "%s";
                """ % (external_id, uniprot_id)
                )

    cursor.close()

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user")
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db")

    (options, args) = parser.parse_args()

    if len(args) != 1:
        sys.stderr.write('%s\n' % __doc__)
        sys.exit(1)

    fname = args[0]

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

    exit_val = 0

    try:
        main(fname, conn)
        conn.commit()
    #     print 'Done committing'
    # except:
    #     print "Unexpected error:", sys.exc_info()[0]
    #     print 'Not committing'
        print('Done committing')
    except Exception as e:
        print("Unexpected error:", str(e))
        print('Not committing')
        conn.rollback()
        exit_val = 1
    finally:
        conn.close()
    sys.exit(exit_val)
