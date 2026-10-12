#!/usr/bin/env python

import pdb

class Interaction:
    def __init__(self, eid1, eid2):
        self.eid1, self.eid2 = self._check_and_swap(eid1, eid2)
        self.types        = []
        self.detections   = []
        self.scores       = []
        self.publications = []
        self.externals    = []

    def _check_and_swap(self, eid1, eid2):
        eid1, eid2 = int(eid1), int(eid2)
        if eid1 > eid2:
            return eid2, eid1
        else:
            return eid1, eid2

    def add_types(self, dbsource_id, external_id, interaction_types):
        for interaction_type in interaction_types:
            self.types.append( [dbsource_id, external_id, interaction_type] )

    def add_detections(self, dbsource_id, external_id, detection_methods):
        for detection_method in detection_methods:
            self.detections.append( [dbsource_id, external_id, detection_method] )

    def add_scores(self, dbsource_id, external_id, scores):
        for score in scores:
            self.scores.append( [dbsource_id, external_id, score] );

    def add_publications(self, dbsource_id, external_id, pmids):
        for pmid in pmids:
            self.publications.append( [dbsource_id, external_id, pmid] )

    def add_external(self, dbsource_id, external_id):
        self.externals.append( [dbsource_id, external_id] )

    def insert(self, cursor):
        """
        Called when interaction was not found inside the database
        """
        self._insert(cursor)
        self._insert_externals(cursor)
        self._insert_types(cursor)
        self._insert_detections(cursor)
        self._insert_scores(cursor)
        self._insert_publications(cursor)

    def update(self, cursor):
        """
        Called when interaction was already found inside the database.
        Deletes externals, types, detections, etc... first and then inserts.
        """
        self.interaction_id = self._get_id(cursor)
        self._update(cursor)

        self._delete_externals(cursor)
        self._delete_types(cursor)
        self._delete_detections(cursor)
        self._delete_scores(cursor)
        self._delete_publications(cursor)

        self._insert_externals(cursor)
        self._insert_types(cursor)
        self._insert_detections(cursor)
        self._insert_scores(cursor)
        self._insert_publications(cursor)

    def append(self, cursor):
        """
        Called when interaction is already found inside the database,
        Does NOT deletes externals, types, detections, etc... first and then inserts.
        """
        self.interaction_id = self._get_id(cursor)

        self._insert_externals(cursor)
        self._insert_types(cursor)
        self._insert_detections(cursor)
        self._insert_scores(cursor)
        self._insert_publications(cursor)

    def _get_id(self, cursor):
        cursor.execute('select id from interactions where entrez_id1 = %s '
                       'and entrez_id2 = %s',
                       (self.eid1, self.eid2))
        row = cursor.fetchone()
        return int(row[0])

    def _update(self, cursor):
        cursor.execute('update interactions set valid = 1 where id = %s', (self.interaction_id,))

    def _insert(self, cursor):
        cursor.execute('insert ignore into interactions (entrez_id1, entrez_id2, valid)'
                       'values (%s, %s, 1)',
                       (self.eid1, self.eid2))

        self.interaction_id = cursor.lastrowid

    def _insert_externals(self, cursor):
        # make sure list is unique
        self.externals = [list(x) for x in set(tuple(x) for x in self.externals)]

        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'insert ignore into interaction2externals (interaction_id, dbsource_id, external_id) '
                'values (%s, %s, %s)',
                (self.interaction_id, dbsource_id, external_id)
            )

    def _insert_types(self, cursor):
        # make sure list is unique
        self.types = [list(x) for x in set(tuple(x) for x in self.types)]

        for dbsource_id, external_id, interaction_type in self.types:
            cursor.execute(
                'insert ignore into interaction2types (dbsource_id, external_id, interaction_type) '
                'values (%s, %s, %s)',
                (dbsource_id, external_id, interaction_type)
            )

    def _insert_detections(self, cursor):
        # make sure list is unique
        self.detections = [list(x) for x in set(tuple(x) for x in self.detections)]

        for dbsource_id, external_id, detection_method in self.detections:
            cursor.execute(
                "insert ignore into interaction2detections (dbsource_id, external_id, detection_method)"
                " values (%s, %s, %s)",
                (dbsource_id, external_id, detection_method)
            )

    def _insert_scores(self, cursor):
        # make sure list is unique
        self.scores = [list(x) for x in set(tuple(x) for x in self.scores)]

        for dbsource_id, external_id, score in self.scores:
            cursor.execute(
                "insert ignore into interaction2scores (dbsource_id, external_id, score) "
                "values (%s, %s, %s)",
                (dbsource_id, external_id, score)
            )

    def _insert_publications(self, cursor):
        # make sure list is unique
        self.publications = [list(x) for x in set(tuple(x) for x in self.publications)]

        for dbsource_id, external_id, pmid in self.publications:
            cursor.execute(
                "insert ignore into interaction2publications (dbsource_id, external_id, pmid) "
                "values (%s, %s, %s)",
                (dbsource_id, external_id, pmid)
            )

    def _delete_externals(self, cursor):
        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'delete from interaction2externals where interaction_id =%s and '
                'dbsource_id = %s and external_id = %s',
                (self.interaction_id, dbsource_id, external_id)
            )

    def _delete_types(self, cursor):
        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'delete from interaction2types where dbsource_id = %s and '
                'external_id = %s',
                (dbsource_id, external_id)
            )

    def _delete_detections(self, cursor):
        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'delete from interaction2detections where dbsource_id = %s and '
                'external_id = %s',
                (dbsource_id, external_id)
            )

    def _delete_scores(self, cursor):
        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'delete from interaction2scores where dbsource_id = %s and  '
                'external_id = %s',
                (dbsource_id, external_id)
            )

    def _delete_publications(self, cursor):
        for dbsource_id, external_id in self.externals:
            cursor.execute(
                'delete from interaction2publications where dbsource_id = %s and '
                'external_id = %s',
                (dbsource_id, external_id)
            )

