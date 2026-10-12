#!/usr/bin/env python

import sys
import re

class MitabParser:
    def __init__(self, dbsource_id):
        self.dbsource_id    = dbsource_id
        self.mi_pattern     = re.compile("MI:\d{4}")
        self.pubmed_pattern = re.compile("pubmed:\d+")
        self.entrez_pattern = re.compile("entrez gene/locuslink:(\d+)")

    def parse(self, fname, interactions):
        with open(fname, 'r') as f:
            next(f)
            for line in f:
                columns = line.strip().split('\t')
                taxid1 = int(columns[9].split(':')[1])
                taxid2 = int(columns[10].split(':')[1])
                if taxid1 != 9606 or taxid2 != 9606:
                    continue
                
                gene1 = columns[0]
                gene2 = columns[1]

                m    = self.entrez_pattern.match(gene1)
                eid1 = int(m.group(1))

                m    = self.entrez_pattern.match(gene2)
                eid2 = int(m.group(1))

                detection_methods = self.parse_mi(columns[6])
                interaction_types = self.parse_mi(columns[11])
                pmids             = self.parse_pmids(columns[8])
                external_id       = columns[13]
                scores            = self.parse_scores(columns[14])

                interaction = interactions.get(eid1, eid2)
                interaction.add_external(self.dbsource_id, external_id)
                interaction.add_types(self.dbsource_id, external_id, interaction_types)
                interaction.add_detections(self.dbsource_id, external_id, detection_methods)
                interaction.add_scores(self.dbsource_id, external_id, scores)
                interaction.add_publications(self.dbsource_id, external_id, pmids)

    def parse_scores(self, string):
        if string == '-':
            return []

        cols = string.split('|')
        cols = map(lambda score: score.split(':')[1], cols)
        return map(lambda score: float(score), cols)

    def parse_pmids(self, string):
        cols = string.split('|')

        retval = []
        for col in cols:
            s = self.pubmed_pattern.search(col)
            if s:
                pmid = s.group(0).split(':')[1] # 'pubmed:15961401'
                retval.append( int(pmid) )

        return retval

    def parse_mi(self, string):
        cols = string.split('|')

        return [self.mi_pattern.search(c).group(0) for c in cols
                if self.mi_pattern.search(c)]
