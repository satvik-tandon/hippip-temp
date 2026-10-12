#!/usr/bin/python3
#####!/usr/local/bin/python
#####!/usr/local/bin/python2.7
#####!/usr/bin/env python
####!/usr/local/bin/python
####!/home/madhavi/python/bin/python2.7
####!/usr/bin/python
####!/usr/local/bin/python2.7
from __future__ import division

import sys
import networkx as nx
# import MySQLdb
import mysql.connector
from optparse import OptionParser
from fisher import pvalue
import numpy as np
from time import time

# Adapted from:
# statsmodels.sandbox.stats.multicomp fdrcorrection0
def fdrc(pvals):
    pvals = np.asarray(pvals)

    pvals_sortind = np.argsort(pvals)
    pvals_sorted = pvals[pvals_sortind]
    sortrevind = pvals_sortind.argsort()

    pvals_corrected_raw = pvals_sorted / (np.arange(1,len(pvals_sorted)+1)/len(pvals_sorted))
    try:
        pvals_corrected = np.minimum.accumulate(pvals_corrected_raw[::-1])[::-1]
        pvals_corrected[pvals_corrected>1] = 1
        return pvals_corrected[sortrevind]
    except ValueError:
        return []

def get_graph_frequencies(gene_map,graph):
    freq_map = {}
    for gene in graph:
        try:
            for term in gene_map[gene]:
                try:
                    freq_map[term] += 1
                except KeyError:
                    freq_map[term] = 1
        except KeyError:
            continue
    return freq_map

def enrich(graph,gene_map,go_freq,conn):
    cursor = conn.cursor()
    genes = list(graph.nodes())
    # print(list(genes))
    avg_time = 0
    for i in range(len(genes)):
        t0 = time()
        gene = genes[i]

        # sys.stdout.write("Gene %s, %d\n" % (gene, i))
        # sys.stdout.flush()
        # sys.stdout.write("\tGene %s: %d/%d, About %d minutes remaining\r" % (gene, i,len(genes),((len(genes) - 1) * avg_time) / 60))
        # sys.stdout.flush()
        try:
            # Find terms of immediate interactors
            neighbors = graph[gene]
            local_terms = {}
            for neighbor in neighbors:
                try:
                    for term in gene_map[neighbor]:
                        try:
                            local_terms[term] += 1
                        except KeyError:
                            local_terms[term] = 1
                except KeyError:
                    continue

            # Compute enrichments from those terms
            result = []
            for term in local_terms:
                a = local_terms[term] # Selected successes
                b = go_freq[term] - a # Unselected successes
                c = len(neighbors) - a # Selected failures
                d = len(graph.nodes()) - go_freq[term] - c # Unselected failures
                result.append((term,pvalue(a,b,c,d).right_tail))
            result_corrected = fdrc([x[1] for x in result])
            #print gene
            count = 0
            for i in range(len(result)):
                if result_corrected[i] < 0.05:
                    count += 1
                    term = result[i][0]
                    p_value = result[i][1]
                    p_value_corr = result_corrected[i]
                    #print "\t%s (%f)" % (r[0],r[1])
                    cursor.execute("INSERT INTO entrez2enriched_go_terms (entrez_id, go_id, pvalue, pvalue_corr) VALUES (%s, %s, %s, %s)",(gene,term,p_value,p_value_corr))
            conn.commit()
        except KeyError:
            continue
        tf = time()
        avg_time = (avg_time * i + (tf - t0)) / (i + 1)
    sys.stderr.write("\n")

def parse_gene2go(file,taxon):
    taxon = str(taxon)

    eid_map = {}
    for line in file:
        if len(line) == 0 or line[0] == '#':
            continue

        # Parse relevant data
        tax_id, gene_id, go_id, evidence, qualifier, go_name, pmid, category = line.strip().split('\t')
        if (taxon is None or tax_id == taxon) and qualifier != 'NOT' and category == 'Process':
            try:
                eid_map[gene_id].append(go_id)
            except KeyError:
                eid_map[gene_id] = [go_id]

    # Remove duplicates
    #eid_map = {g: list(set(eid_map[g])) for g in eid_map} 
## Madhavi 2020/3/29
## replaced above line with the following two lines as thye didnt work with 2.6 python
    for g in eid_map:
        eid_map[g] = list(set(eid_map[g]))

    return eid_map

def get_annotations(cursor):
    eid_map = {}
    cursor.execute("SELECT entrez_id, go_id FROM go_annotations")
    for row in cursor.fetchall():
        try:
            eid_map[str(row[0])].append(str(row[1]))
        except KeyError:
            eid_map[str(row[0])] = [str(row[1])]
    return eid_map

def get_parents(term,obo):
    parents = [term]

    try:
        for parent in obo[term]['is_a']:
            parents += get_parents(parent,obo)
    except KeyError:
        pass

    return parents

def propagate(gene_map,obo):
    new_gene_map = {}
    for gene in gene_map:
        new_terms = []
        for term in gene_map[gene]:
            new_terms += get_parents(term,obo)
        new_gene_map[gene] = list(set(new_terms + gene_map[gene]))

    return new_gene_map

def parse_obo(file):
    terms = {}
    id = ''
    parents = []
    namespace = ''
    for line in file:
        if line[0] == '[':
            if namespace == 'biological_process':
                terms[id] = {'is_a': parents}
            id = ''
            parents = []
            namespace = ''
        elif line[:3] == 'id:':
            id = line.strip()[4:]
        elif line[:5] == 'is_a:':
            parents.append(line.strip()[6:16])
        elif line[:10] == 'namespace:':
            namespace = line.strip()[11:]
    return terms

if __name__ == '__main__':
    usage = "Usage: %proc [options] gene_ontology_ext.obo"
    parser = OptionParser(usage=usage)
    parser.add_option("-d", "--database", dest="db", help="database to read from")
    parser.add_option("-u", "--user", dest="user", help="MySQL user")
    parser.add_option("-p", "--password", dest="passwd", help="MySQL password")
    (options, args) = parser.parse_args()

    #obo_file, gene2go = args
    obo_file = args[0]

    # Connect to MySQL database
    if options.db is None:
        #sys.stderr.write('MySQL dbname: ')
        #options.db = sys.stdin.readline().rstrip()
        options.db = input("MySQL dbname: ").strip()
    if options.user is None:
        #sys.stderr.write('MySQL username: ')
        #options.user = sys.stdin.readline().rstrip()
        options.user = input("MySQL username: ").strip()
    if options.passwd is None:
        import getpass
        options.passwd = getpass.getpass('MySQL password: ',sys.stderr)

    conn = mysql.connector.connect(
        host='localhost',
        db=options.db,
        user=options.user,
        passwd=options.passwd,
    )

    cursor = conn.cursor()

    # Load interactome
    sys.stderr.write("Loading interactome\n")
    I = nx.Graph()
    cursor.execute("SELECT entrez_id1, entrez_id2 FROM valid_direct_interactions")
    I.add_edges_from([(str(x[0]),str(x[1])) for x in cursor.fetchall()])

    # Parse the obo file
    sys.stderr.write("Parsing obo file\n")
    go_terms = None
    with open(obo_file,'r') as file:
        go_terms = parse_obo(file)

    # Parse the gene2go file
    # sys.stderr.write("Parsing gene2go file\n")
    #gene_map = None
    #with open(gene2go,'r') as file:
    #    gene_map = parse_gene2go(file,9606)

    # Get the GO annotations from the database
    sys.stderr.write("Reading GO annotations\n")
    gene_map = get_annotations(cursor)


    # Propagate
    sys.stderr.write("Propagating annotations\n")
    gene_map = propagate(gene_map,go_terms)

    # Calculate frequencies
    sys.stderr.write("Computing annotation frequencies\n")
    go_freq = get_graph_frequencies(gene_map,I)

    # Print pr-stats
    sys.stderr.write("Graph: %d edges between %d nodes\n" % (len(I.edges()), len(I.nodes())))
    sys.stderr.write("GO Annotations: %d annotated genes, %d found in graph\n" % (len(gene_map),len(set(gene_map.keys()) & set(I.nodes()))))

    # Compute enrichments
    sys.stderr.write("Computing enrichments\n")
    enrich(I,gene_map,go_freq,conn)
