#!/usr/bin/env python

import sys
#import MySQLdb
import mysql.connector
import getpass

from interaction import Interaction
from interactions import Interactions
import update

def load_interactions(fname, dbsource_id):
    interactions = Interactions()
    with open(fname, 'r') as f:
        external_id = 1
        for line in f:
            cols = line.strip().split('\t')
            eid1, eid2 = int(cols[0]), int(cols[1])
            interaction = Interaction(eid1, eid2)
            interaction.add_external(dbsource_id, external_id)
            interaction.add_types(dbsource_id, external_id, ['MI:0110']) # predicted interaction
            interaction.add_detections(dbsource_id, external_id, ['MI:0110']) #
            interaction.add_scores(dbsource_id, external_id, ['MI:0110']) #

            interactions.add(interaction)
            external_id += 1
    return interactions

def main(fname, conn):
    dbname = 'hippip'
    url    = 'http://severus.dbmi.pitt.edu/'
    dbsource_id = update.get_or_set_dbsource_id(conn, dbname, url)

    new_interactions = load_interactions(fname, dbsource_id)
    existing_interactions = update.get_existing_interactions(conn)

    print('inserting...')
    for new_interaction in new_interactions.iter():
        if not update.is_valid_gene(new_interaction.eid1) or \
           not update.is_valid_gene(new_interaction.eid2):
            continue
    
        if existing_interactions.contains(new_interaction.eid1, new_interaction.eid2):
            new_interaction.append(cursor)
        else:
            new_interaction.insert(cursor)
    print('done inserting')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.stderr.write('')
        sys.exit(1)
    fname = sys.argv[1]

    #print 'MySQL dbname: ',
    #db = sys.stdin.readline().rstrip()
    db = input("MySQL dbname: ")
    #print 'MySQL username: ',
    #user = sys.stdin.readline().rstrip()
    user = input("MySQL username").strip()
    passwd = getpass.getpass('MySQL password: ')

    conn = mysql.connector.connect(
        host='localhost',
        db=db,
        user=user,
        passwd=passwd,
    )

    try:
        main(fname, conn)
        conn.commit()
        print('Done committing')
    except:
        print( "Unexpected error:", sys.exc_info()[0])
        print('Not committing')
        conn.rollback()
    finally:
        conn.close()

