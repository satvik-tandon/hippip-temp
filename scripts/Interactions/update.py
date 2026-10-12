#!/usr/bin/python

"""Usage:
    python update.py

Inserts/updates the interaction related tables in the specified database.
"""

# import os
import sys
# import MySQLdb
import mysql.connector
# import pdb
# import re
import getpass
# import logging
import traceback

from mitab import MitabParser
from psimi import PsimiParser
from hippip import HippipParser

from interaction import Interaction
from interactions import Interactions

from json import load
from optparse import OptionParser

def get_existing_interactions(conn):
    cursor = conn.cursor()
    cursor.execute("select entrez_id1, entrez_id2 from interactions")
    rows = cursor.fetchall()

    interactions = Interactions()
    for row in rows:
        eid1, eid2 = row[0], row[1]
        interaction = Interaction(eid1, eid2)
        interactions.add(interaction)

    cursor.close()
    return interactions

def get_or_set_dbsource_id(conn, dbname, url):
    cursor = conn.cursor()

    cursor.execute('select id from dbsources where name = %s', (dbname,) )
    dbsource_id = cursor.fetchone()

    if dbsource_id:
        dbsource_id = dbsource_id[0]
    else:
        cursor.execute('insert into dbsources (name, url) values (%s, %s)', (dbname, url) )
        dbsource_id = cursor.lastrowid

    cursor.close()
    return int(dbsource_id)


def load_new_interactions(conn, dbsources):
    interactions = Interactions()

    for dbsource in dbsources:
        fname = dbsource['filename']
        dbname = dbsource['databasename']
        url = dbsource['url']
        fformat = dbsource['fileformat']
        sys.stdout.write('%s\n' % fname)

        dbsource_id = get_or_set_dbsource_id(conn, dbname, url)
        if fformat == 'mitab':
            parser = MitabParser(dbsource_id)
        elif fformat == 'psimi':
            parser = PsimiParser(dbsource_id,conn)
        elif fformat == 'hippip':
            parser = HippipParser(dbsource_id)
        else:
            raise Exception("unknown format!")

        parser.parse(fname, interactions)
    return interactions

def is_valid_gene(eid, cursor):
    cursor.execute("SELECT EXISTS(SELECT 1 FROM genes WHERE id = %d)" % (eid))
    return bool(cursor.fetchone()[0])

def main(dbsources, conn):
    cursor = conn.cursor()
    cursor.execute("update interactions set valid = 1") # ugly hack to update valid=0
    cursor.execute("update interactions set valid = 0")

    existing_interactions = get_existing_interactions(conn)
    new_interactions      = load_new_interactions(conn, dbsources)
    #Madhavi MKG
    print("Done here")
    for new_interaction in new_interactions.iter():
        if not is_valid_gene(new_interaction.eid1, cursor) or not is_valid_gene(new_interaction.eid2, cursor):
            continue

        if existing_interactions.contains(new_interaction.eid1, new_interaction.eid2):
            new_interaction.update(cursor)
        else:
            new_interaction.insert(cursor)

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user")
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db")

    (options, args) = parser.parse_args()

    if len(args) != 1:
        sys.stderr.write('%s\n' % __doc__)
        sys.exit(1)

    dbsources = load(open(args[0]))

    db = None
    user = None
    passwd = None

    if options.db:
        db = options.db
    else:
        # print 'MySQL database: ',
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
        main(dbsources, conn)
        conn.commit()
        print ('Done committing')
    except:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        print ("Unexpected error:"), sys.exc_info()[0]
        print ("*** print_tb:")
        traceback.print_tb(exc_traceback)
        print ("*** print_exception:")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        print ('Not committing')
        conn.rollback()
        exit_val = 1
    finally:
        conn.close()
        sys.exit(exit_val)
