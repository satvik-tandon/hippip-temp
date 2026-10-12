#!/usr/bin/python

"""Usage:
    python insert_diseases.py /path/to/disease_file

Parses KEGG disease file and inserts it into database
"""

import sys
import getpass
# import pdb
import re
from optparse import OptionParser
import mysql.connector
# import MySQLdb

def cleanse_names(names):
    """remove '[DS:H00064]' from disease name"""
    retval = []
    for name in names:
        name = re.sub(r' \[DS:H\d{5}\]', r'', name)
        retval.append(name)
    return retval

def read_file(fname):
    gene_pattern = re.compile('\[HSA:(.+?)\]')

    data               = {} # store information about disease (id, name, category_id)
    gene2disease       = {} # store mapping from entrez_id to disease_ids
    disease_categories = {} # stores mapping from string to int
    disease_cat_id     = 1

    f = open(fname)
    is_gene   = False
    is_drug   = False
    is_name   = False

    entry = ''
    cat_id = ''

    with open(fname, 'r') as f:
        for line in f:
            if not line.startswith(' '):
                is_gene, is_drug, is_name = False, False, False

            if line.startswith('///'):
                # end of a entry
                name = cleanse_names(name)

                data[entry] = {}
                data[entry]['name'] = ' '.join(name)
                if cat_id:
                    data[entry]['category_id'] = cat_id

            if line.startswith('ENTRY'):
                entry = line.strip().split()[1]
            elif line.startswith('GENE'):
                is_gene = True
            elif line.startswith('CATEGORY'):
                category = ' '.join(line.strip().split()[1:])

                if not category in disease_categories:
                    disease_categories[category] = disease_cat_id
                    disease_cat_id += 1
                cat_id = disease_categories[category]
            elif line.startswith('NAME'):
                name = [' '.join(line.strip().split()[1:])]
                is_name = True

            if is_gene:
                res = gene_pattern.search(line)
                if res:
                    genes = res.groups()[0].split()
                    for gene in genes:

                        if gene in gene2disease:
                            gene2disease[gene].append(entry)
                        else:
                            gene2disease[gene] = [entry]
            # second time and later
            if line.startswith(' ') and is_name:
                name.append( line.strip() )

    return data, gene2disease, disease_categories

def insert(cursor, disease_data, gene2disease, disease_categories, dbsource_id):
    diseases = list(disease_data.keys())
    diseases.sort(key=lambda s: int(s[1:]))

    external_id_to_local_id = {}

    for disease in diseases:
        name        = disease_data[disease]['name']
        external_id = disease

        cursor.execute(
            'insert into diseases (name, dbsource_id, external_id) values (%s, %s, %s)',
            (name, dbsource_id, external_id)
        )

        local_id = int(cursor.lastrowid)
        external_id_to_local_id[external_id] = local_id

    insert_values = []
    genes = gene2disease.keys()
    genes = list(set(genes))
    genes.sort(key=lambda num: int(num))
    for gene in genes:
        diseases = gene2disease[gene]
        diseases = list(set(diseases)) # make sure its unique
        diseases = map(lambda disease: external_id_to_local_id[disease], diseases)
        for disease in diseases:
            insert_values.append( (gene, disease) )

    cursor.executemany(
        'insert into entrez2diseases (entrez_id, disease_id)'
        'values (%s, %s)',
        insert_values
    )

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

def main(fname, conn):
    dbsource_id = get_or_set_dbsource_id(conn, "KEGG Disease", "http://www.genome.jp/kegg/disease/")

    cursor = conn.cursor()
    disease_data, gene2disease, disease_categories = read_file(fname)
    insert(cursor, disease_data, gene2disease, disease_categories, dbsource_id)
    cursor.close()

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-u", "--username", dest="user")
    parser.add_option("-p", "--password", dest="passwd")
    parser.add_option("-d", "--database", dest="db")

    (options, args) = parser.parse_args()

    if len(args) != 1:
        print ('Usage: python insert_disease.py /path/to/kegg_diseases')
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
    #     print "Unexpected error:", sys.exc_info()
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
