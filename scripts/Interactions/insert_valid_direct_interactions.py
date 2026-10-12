#!/usr/bin/python

"""Usage:
    python insert_valid_direct_interactions.py

Reads in information from `interactions`, `interaction2externals`, `interaction2types` tables
and inserts information into `valid_direct_interactions` table.
"""

import sys
import getpass
#import MySQLdb
import mysql.connector
from optparse import OptionParser

def get_valid_direct_interactions(cursor):
    query="""
        SELECT 
            i.id AS id,
            i.entrez_id1 AS eid1,
            i.entrez_id2 AS eid2
        FROM
            interactions i
            INNER JOIN interaction2externals i2e
                ON i.id = i2e.interaction_id
            INNER JOIN interaction2types i2t
                ON i2e.dbsource_id = i2t.dbsource_id
                AND i2e.external_id = i2t.external_id
        WHERE
            i.valid = 1
            AND i2t.interaction_type = 'MI:0407'
            AND i.entrez_id1 != i.entrez_id2
        GROUP BY id
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    return rows


def is_predicted_known(cursor, interaction_id):
    query="""
        SELECT EXISTS(
            SELECT 1
            FROM interaction2externals
            JOIN dbsources
            ON interaction2externals.dbsource_id = dbsources.id
            WHERE dbsources.name = "hippip"
            AND interaction2externals.interaction_id = %d
        )
    """
    cursor.execute(query % (interaction_id))
    predicted = cursor.fetchone()[0]
    
#    query="""
#        SELECT EXISTS(
#            SELECT 1
#            FROM interaction2externals
#            JOIN dbsources
#            ON interaction2externals.dbsource_id = dbsources.id
#            WHERE dbsources.name != "hippip"
#            AND interaction2externals.interaction_id = %d
#        )
#    """
    query="""
        SELECT EXISTS(
            SELECT 1
            FROM (
                SELECT dbsource_id, external_id
                FROM interaction2externals
                WHERE interaction_id = %d)
            AS i2e
            JOIN (
                SELECT id
                FROM dbsources
                WHERE name != "hippip"
            ) AS dbs
                ON i2e.dbsource_id = dbs.id
            JOIN interaction2types i2t
                ON i2e.dbsource_id = i2t.dbsource_id
                AND i2e.external_id = i2t.external_id
            WHERE
                i2t.interaction_type = 'MI:0407'
        )
    """

    cursor.execute(query % (interaction_id))
    known = cursor.fetchone()[0]

    return predicted, known


def main(conn):
    cursor = conn.cursor()
    cursor.execute('delete from valid_direct_interactions')

    valid_direct_interactions = get_valid_direct_interactions(cursor)

    for i in valid_direct_interactions:
        interaction_id = i[0]
        entrez_id1 = i[1]
        entrez_id2 = i[2]

        predicted, known = is_predicted_known(cursor, interaction_id)
        if predicted == 1 or known == 1 :
            cursor.execute(
                '''insert into valid_direct_interactions (id, entrez_id1, entrez_id2, known, predicted)
                values (%s, %s, %s, %s, %s)''', (interaction_id, entrez_id1, entrez_id2, known, predicted)
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
        #print 'MySQL database: ',
        #db = sys.stdin.readline().rstrip()
        db = input("MySQL database: ").strip()
    if options.user:
        user = options.user
    else:
        #print 'MySQL username: ',
        #user = sys.stdin.readline().rstrip()
        user = input("MySQL username: ").strip()
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
        print("Unexpected error:", sys.exc_info())
        print('Not committing')
        conn.rollback()
        exit_val = 1
    finally:
        conn.close()
    sys.exit(exit_val)
