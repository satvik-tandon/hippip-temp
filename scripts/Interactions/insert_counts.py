#!/usr/bin/env python

"""Usage:
    python insert_counts.py

(Deletes) and inserts into
- entrez2pathways_count
- entrez2drugs_count
- entrez2diseases_count
"""

import sys
import getpass

#import MySQLdb
import mysql.connector

def get_all_genes(cursor):
    # query ="""
    #     select distinct(entrez_id1) as eid from valid_direct_interactions
    #     union
    #     select distinct(entrez_id2) as eid from valid_direct_interactions
    #     order by eid
    # """
    query ="""
        select distinct(id) as eid from genes
        order by eid
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    return map(lambda row: int(row[0]), rows)

def get_count(eid, cursor):
    query = """
        select count(entrez_id) from entrez2pathways where entrez_id = %s
    """
    cursor.execute(query, eid)
    pathways_count = int(cursor.fetchone()[0])

    query = """
        select count(entrez_id) from entrez2drugs where entrez_id = %s
    """
    cursor.execute(query, eid)
    drugs_count = int(cursor.fetchone()[0])

    query = """
        select count(entrez_id) from entrez2diseases where entrez_id = %s
    """
    cursor.execute(query, eid)
    diseases_count = int(cursor.fetchone()[0])

    return pathways_count, drugs_count, diseases_count

def main(conn):
    cursor = conn.cursor()
    cursor.execute('delete from entrez2pathways_count')
    cursor.execute('delete from entrez2drugs_count')
    cursor.execute('delete from entrez2diseases_count')

    genes = get_all_genes(cursor)

    for gene in genes:
        pathways_count, drugs_count, diseases_count = get_count(gene, cursor)

        cursor.execute(
            '''insert into entrez2pathways_count (entrez_id, count)
            values (%s, %s)''',
            (gene, pathways_count)
        )

        cursor.execute(
            '''insert into entrez2drugs_count (entrez_id, count)
            values (%s, %s)''',
            (gene, drugs_count)
        )

        cursor.execute(
            '''insert into entrez2diseases_count (entrez_id, count)
            values (%s, %s)''',
            (gene, diseases_count)
        )
    cursor.close()

if __name__ == '__main__':
    #print 'MySQL dbname: ',
    db = input("MySQL dbname: ").strip()
    #print 'MySQL username: ',
    user = input('MySQL username').strip()
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
        print("Unexpected error:", sys.exc_info()[0], sys.exc_info()[1])
        print('Not committing')
        conn.rollback()
        exit_val = 1
    finally:
        conn.close()
    sys.exit(exit_val)
