#!/usr/bin/env python

# import MySQLdb
import getpass
import xml.etree.cElementTree as et
import sys
import re
import mysql.connector
import pdb

class PsimiParser:
    def __init__(self, dbsource_id, conn):
        self.dbsource_id = dbsource_id
        self.mi_pattern  = re.compile("MI:\d{4}")
        self.conn = conn

    def _parse(self, fname):
        tree = et.parse(fname)
        xmlns = tree.getroot().tag[1:].split("}")[0] # ugly hack
        self.xmlns = xmlns

        experiments  = tree.getroot().find('{%s}entry/{%s}experimentList'  % (xmlns, xmlns))
        # interactors  = tree.getroot().find('{%s}entry/{%s}interactorList'  % (xmlns, xmlns))
        self.interactions = tree.getroot().find('{%s}entry/{%s}interactionList' % (xmlns, xmlns))
        self.experiments  = self.parse_experiments(experiments)

    def parse_experiments(self, experiments):
        retval = {}

        for experiment in experiments:
            pmids = set()
            bibrefs = experiment.find('{%s}bibref' % self.xmlns)
            for bibref in bibrefs:
                for ref in bibref:
                    if ref.attrib['refTypeAc'] == 'MI:0358':
                        pmids.add( int(ref.attrib['id']) )

            pmids = sorted(list(pmids))

            detection = experiment.find('{%s}interactionDetectionMethod' % self.xmlns)
            detection_method = ''
            if detection:
                method = detection.find(
                    '{%s}xref/{%s}primaryRef' % (self.xmlns, self.xmlns)
                ).attrib['id']

                if self.mi_pattern.match(method):
                    detection_method = method

            experiment_id = experiment.attrib['id']
            retval[experiment_id] = {}
            retval[experiment_id]['pmids'] = pmids
            retval[experiment_id]['detection'] = detection_method

        return retval

    def get_entrez_ids(self, participants):
        hprd_id1 = participants[0].find('{%s}interactorRef' % (self.xmlns)).text
        hprd_id2 = participants[1].find('{%s}interactorRef' % (self.xmlns)).text

        cursor = self.conn.cursor()
        query = """
            SELECT entrez_id
            FROM entrez2hprd
            WHERE hprd_id = %d
        """
        try:
            cursor.execute(query % (int(hprd_id1)))
            eid1 = cursor.fetchone()[0]
            cursor.execute(query % (int(hprd_id2)))
            eid2 = cursor.fetchone()[0]

            return eid1, eid2
        except:
            return None, None

    def get_interaction_type(self, interaction):
        interaction_type = interaction.find('{%s}interactionType' % (self.xmlns))

        if interaction_type:
            t = interaction_type.find(
                '{%s}xref/{%s}primaryRef' % (self.xmlns, self.xmlns)
            ).attrib['id']
            return [t]
        else:
            return ['MI:0407']

    def get_experiment_ids(self, interaction):
        experiments = interaction.find('{%s}experimentList' % (self.xmlns))

        retval = []
        for experiment in experiments:
            retval.append( experiment.text )
        return retval

    def get_detection_methods(self, experiment_ids):
        detection_methods = set()

        for experiment_id in experiment_ids:
            detection_methods.add( self.experiments[experiment_id]['detection'] )
        return sorted(list(detection_methods))

    def get_pmids(self, experiment_ids):
        pmids = set()

        for experiment_id in experiment_ids:
            ps = self.experiments[experiment_id]['pmids']
            for p in ps:
                pmids.add(p)
        return sorted(list(pmids))

    def parse(self, fname, interactions):
        self._parse(fname)
        for interaction in self.interactions:
            participants = interaction.find('{%s}participantList' % (self.xmlns))
            if len(participants) > 2:
                continue

            eid1, eid2 = self.get_entrez_ids(participants)

            if not eid1 or not eid2:
                continue

            experiment_ids = self.get_experiment_ids(interaction) # done

            detection_methods = self.get_detection_methods(experiment_ids)
            interaction_types = self.get_interaction_type(interaction) # done
            pmids             = self.get_pmids(experiment_ids)
            external_id       = interaction.attrib['id']
            # scores            = self.get_scores(interaction)

            # print '%s\t%s\t%s' % (experiment_ids, eid1, eid2)

            interaction = interactions.get(eid1, eid2)
            interaction.add_external(self.dbsource_id, external_id)
            interaction.add_types(self.dbsource_id, external_id, interaction_types)
            interaction.add_detections(self.dbsource_id, external_id, detection_methods)
            # interaction.add_scores(self.dbsource_id, external_id, scores)
            interaction.add_publications(self.dbsource_id, external_id, pmids)

def main(conn):
    parser = PsimiParser('hprd', conn)
    fname = '/data01/backup/hprd/HPRD_SINGLE_PSIMI_041210.xml'
    interactions = []
    parser.parse(fname, interactions)

if __name__ == '__main__':

    #print ('MySQL dbname: '),
    #db = sys.stdin.readline().rstrip()
    #print ('MySQL username: ',)
    #user = sys.stdin.readline().rstrip()
    db = input("MySQL dbname: ").strip()
    user = input("MySQL username:").strip()
    passwd = getpass.getpass('MySQL password: ')

    conn = mysql.connector.connect(
        host='localhost',
        db=db,
        user=user,
        passwd=passwd,
    )

    main(conn)
