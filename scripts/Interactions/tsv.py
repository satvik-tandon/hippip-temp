#!/usr/bin/env python

"""
For ontology definitions, refer to:
http://obo.cvs.sourceforge.net/viewvc/obo/obo/ontology/genomic-proteomic/protein/psi-mi.obo
"""

class TSVParser:
    def __init__(self, dbsource_id):
        self.dbsource_id        = dbsource_id
        self.interaction_types  = ['MI:0407'] # biophysical interaction
        self.detection_methods  = ['MI:0018'] # Y2H

    def parse(self, fname, interactions):
        external_id = 1
        with open(fname, 'r') as f:
            for line in f:
                cols = line.strip().split('\t')
                eid1, eid2 = int(cols[0]), int(cols[1])
                scores = []
                if len(cols) > 2:
                    scores = [float(cols[2])]

                interaction = interactions.get(eid1, eid2)
                interaction.add_external(self.dbsource_id, external_id)
                interaction.add_types(self.dbsource_id, external_id, self.interaction_types)
                interaction.add_detections(self.dbsource_id, external_id, self.detection_methods)

                if scores:
                    interaction.add_scores(self.dbsource_id, external_id, scores)

                external_id += 1
