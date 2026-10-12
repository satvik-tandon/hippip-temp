# satvvik: Keep table metadata and refresh checkpoints outside the production schema.
import base64
import datetime
import decimal
import hashlib
import json
import sqlite3
from pathlib import Path


class RefreshError(Exception):
    pass


def quote(name):
    return '`' + name.replace('`', '``') + '`'


def qualified(database, table):
    return quote(database) + '.' + quote(table)


# satvvik: Preserve MySQL value types when saving rows in the local JSON/SQLite cache.
def json_default(value):
    if isinstance(value, bytes):
        return {'__bytes__': base64.b64encode(value).decode('ascii')}
    if isinstance(value, decimal.Decimal):
        return {'__decimal__': str(value)}
    if isinstance(value, datetime.datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, datetime.date):
        return {'__date__': value.isoformat()}
    if isinstance(value, datetime.timedelta):
        return {'__seconds__': value.total_seconds()}
    raise TypeError(type(value).__name__)


def json_object(value):
    if '__bytes__' in value:
        return base64.b64decode(value['__bytes__'])
    if '__decimal__' in value:
        return decimal.Decimal(value['__decimal__'])
    if '__datetime__' in value:
        return datetime.datetime.fromisoformat(value['__datetime__'])
    if '__date__' in value:
        return datetime.date.fromisoformat(value['__date__'])
    if '__seconds__' in value:
        return datetime.timedelta(seconds=value['__seconds__'])
    return value


def dumps(value):
    return json.dumps(value, default=json_default, sort_keys=True, separators=(',', ':'), allow_nan=False)


def loads(value):
    return json.loads(value, object_hook=json_object)


# satvvik: Match records by source identifiers or contents when the schema has no unique key.
SPECS = {
    'dbsources': ('name',),
    'genes': ('id',),
    'go_terms': ('id',),
    'go_annotations': ('entrez_id', 'go_id'),
    'psimi_ontologies': ('id',),
    'entrez2hprd': ('entrez_id',),
    'entrez2ensembls': ('entrez_id', 'ensembl_id'),
    'entrez2uniprots': ('entrez_id', 'uniprot_id'),
    'pathways': ('dbsource_id', 'external_id'),
    'entrez2pathways': ('entrez_id', 'pathway_id'),
    'GWAS': ('pubmed_id', 'trait', 'gene_symbol'),
    'entrez2pdbs': ('entrez_id', 'pdb_id'),
    'diseases': ('dbsource_id', 'external_id'),
    'entrez2diseases': ('entrez_id', 'disease_id'),
    'drugs': ('dbsource_id', 'external_id'),
    'entrez2drugs': ('entrez_id', 'drug_id'),
    'atc_codes': ('drug_id', 'atc'),
    'interactions': ('entrez_id1', 'entrez_id2'),
    'interaction2externals': ('interaction_id', 'dbsource_id', 'external_id'),
    'interaction2detections': ('dbsource_id', 'external_id', 'detection_method'),
    'interaction2publications': ('dbsource_id', 'external_id', 'pmid'),
    'interaction2scores': ('dbsource_id', 'external_id', 'score'),
    'interaction2types': ('dbsource_id', 'external_id', 'interaction_type'),
    'valid_direct_interactions': ('id',),
    'valid_direct_interacting_partners': ('entrez_id1', 'entrez_id2'),
    'entrez2enriched_go_terms': ('entrez_id', 'go_id', 'pvalue', 'pvalue_corr'),
    'interaction2centralities': ('interaction_id',),
}

AUTO_ENTITIES = ('dbsources', 'pathways', 'diseases', 'drugs', 'interactions')

# satvvik: Remap staging IDs to persistent IDs in dependent records.
REFERENCES = {
    'pathways': {'dbsource_id': 'dbsources'},
    'diseases': {'dbsource_id': 'dbsources'},
    'drugs': {'dbsource_id': 'dbsources'},
    'entrez2pathways': {'pathway_id': 'pathways'},
    'entrez2diseases': {'disease_id': 'diseases'},
    'entrez2drugs': {'drug_id': 'drugs'},
    'atc_codes': {'drug_id': 'drugs'},
    'interaction2externals': {'interaction_id': 'interactions', 'dbsource_id': 'dbsources'},
    'interaction2detections': {'dbsource_id': 'dbsources'},
    'interaction2publications': {'dbsource_id': 'dbsources'},
    'interaction2scores': {'dbsource_id': 'dbsources'},
    'interaction2types': {'dbsource_id': 'dbsources'},
    'valid_direct_interactions': {'id': 'interactions'},
    'interaction2centralities': {'interaction_id': 'interactions'},
}


class Table:
    def __init__(self, conn, database, name):
        self.name = name
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, COLLATION_NAME, IS_NULLABLE, EXTRA, GENERATION_EXPRESSION '
                           'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s '
                           'ORDER BY ORDINAL_POSITION', (database, name))
            self.metadata = cursor.fetchall()
            cursor.execute('SELECT COLUMN_NAME FROM information_schema.STATISTICS '
                           'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME="PRIMARY" '
                           'ORDER BY SEQ_IN_INDEX', (database, name))
            self.primary = tuple(row['COLUMN_NAME'] for row in cursor.fetchall())
            cursor.execute('SELECT INDEX_NAME,COLUMN_NAME,SUB_PART FROM information_schema.STATISTICS '
                           'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND NON_UNIQUE=0 ORDER BY INDEX_NAME,SEQ_IN_INDEX',
                           (database, name))
            indexes = {}
            for row in cursor.fetchall():
                indexes.setdefault(row['INDEX_NAME'], []).append(row)
            nullable = {row['COLUMN_NAME'] for row in self.metadata if row['IS_NULLABLE'] == 'YES'}
            self.unique = next((tuple(row['COLUMN_NAME'] for row in entries) for entries in indexes.values()
                                if all(row['SUB_PART'] is None and row['COLUMN_NAME'] not in nullable for row in entries)), ())
            cursor.execute('SELECT ENGINE, AUTO_INCREMENT FROM information_schema.TABLES '
                           'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s', (database, name))
            info = cursor.fetchone()
            if not info or info['ENGINE'].lower() != 'innodb':
                raise RefreshError(name + ' must exist and use InnoDB')
            self.next_id = int(info['AUTO_INCREMENT'] or 1)
            cursor.execute('SELECT COUNT(*) AS count FROM information_schema.TRIGGERS '
                           'WHERE TRIGGER_SCHEMA=%s AND EVENT_OBJECT_TABLE=%s', (database, name))
            if cursor.fetchone()['count']:
                raise RefreshError('Cannot preserve insertion behavior while ' + name + ' has triggers')
            cursor.execute('SELECT COUNT(*) AS count FROM information_schema.KEY_COLUMN_USAGE '
                           'WHERE (TABLE_SCHEMA=%s AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL) '
                           'OR (REFERENCED_TABLE_SCHEMA=%s AND REFERENCED_TABLE_NAME=%s)',
                           (database, name, database, name))
            if cursor.fetchone()['count']:
                raise RefreshError('Refresh requires the existing tables without foreign keys: ' + name)
        finally:
            cursor.close()
        if not self.metadata:
            raise RefreshError('Missing table ' + name)
        # satvvik: DEFAULT_GENERATED timestamps are allowed; computed columns need special handling.
        if any(row['GENERATION_EXPRESSION'] for row in self.metadata):
            raise RefreshError('Generated columns need a dedicated refresh adapter: ' + name)
        self.columns = tuple(row['COLUMN_NAME'] for row in self.metadata)
        self.timestamps = tuple(name for name in ('updated_at', 'last_updated') if name in self.columns)
        self.data_columns = tuple(name for name in self.columns if name not in self.timestamps)
        self.storage_key = self.primary or self.unique or SPECS[name]
        self.keys = tuple(dict.fromkeys(self.storage_key + SPECS[name]))
        if not set(self.keys) <= set(self.columns):
            raise RefreshError('Unexpected columns in ' + name)
        # satvvik: Match text keys using MySQL's collation and padding rules.
        self.weights = {}
        for row in self.metadata:
            column = row['COLUMN_NAME']
            if column not in self.keys or not row['COLLATION_NAME']:
                continue
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT PAD_ATTRIBUTE FROM information_schema.COLLATIONS WHERE COLLATION_NAME=%s',
                               (row['COLLATION_NAME'],))
                pad = cursor.fetchone()[0]
            finally:
                cursor.close()
            expression = quote(column)
            if pad == 'PAD SPACE':
                expression += ' AS CHAR(' + str(row['CHARACTER_MAXIMUM_LENGTH']) + ')'
            self.weights[column] = 'HEX(WEIGHT_STRING(' + expression + '))'

    def key(self, row, weights, columns=None):
        return dumps([weights.get(name, row[name]) for name in (columns or self.storage_key)])

    def where(self, row):
        return ' AND '.join(quote(name) + ' <=> %s' for name in self.storage_key), tuple(row[name] for name in self.storage_key)

    def selections(self):
        expressions = [quote(name) for name in self.columns]
        names = list(self.columns)
        for index, name in enumerate(self.weights):
            alias = '__weight_' + str(index)
            expressions.append(self.weights[name] + ' AS ' + quote(alias))
            names.append(alias)
        return expressions, names

    def decode(self, item):
        weights = {name: item.pop('__weight_' + str(index)) for index, name in enumerate(self.weights)}
        return item, weights

    def rows(self, conn, database):
        selections, _ = self.selections()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute('SELECT ' + ','.join(selections) + ' FROM ' + qualified(database, self.name)
                           + ' ORDER BY ' + ','.join(quote(name) for name in self.columns))
            for item in cursor:
                yield self.decode(item)
        finally:
            cursor.close()


# satvvik: Store snapshots, ID mappings and durable batch progress in local SQLite.
class Cache:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path))
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS old_rows '
                          '(t TEXT, k TEXT, payload TEXT, n INTEGER, PRIMARY KEY(t,k))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS wanted_rows '
                          '(t TEXT, k TEXT, payload TEXT, n INTEGER, PRIMARY KEY(t,k))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS entities '
                          '(t TEXT, natural_key TEXT, identifier INTEGER, PRIMARY KEY(t,natural_key))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS id_map '
                          '(t TEXT, source_id INTEGER, target_id INTEGER, PRIMARY KEY(t,source_id))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS progress '
                          '(name TEXT PRIMARY KEY, offset INTEGER NOT NULL)')
        self.conn.commit()

    def close(self):
        self.conn.close()

    def offset(self, name):
        row = self.conn.execute('SELECT offset FROM progress WHERE name=?', (name,)).fetchone()
        return row[0] if row else 0

    def advance(self, name, offset):
        self.conn.execute('INSERT INTO progress(name,offset) VALUES (?,?) '
                          'ON CONFLICT(name) DO UPDATE SET offset=excluded.offset', (name, offset))
        self.conn.commit()

    # satvvik: Preserve duplicate counts, but reject conflicting values for the same record identity.
    def add(self, bucket, table, key, row, count=1):
        if bucket not in ('old_rows', 'wanted_rows'):
            raise RefreshError('Invalid cache bucket')
        encoded = dumps(row)
        old = self.conn.execute('SELECT payload FROM ' + bucket + ' WHERE t=? AND k=?', (table, key)).fetchone()
        if old and old[0] != encoded:
            raise RefreshError('Ambiguous duplicate identity in ' + table)
        self.conn.execute('INSERT INTO ' + bucket + '(t,k,payload,n) VALUES (?,?,?,?) '
                          'ON CONFLICT(t,k) DO UPDATE SET n=n+excluded.n', (table, key, encoded, count))

    def old(self, table, key):
        row = self.conn.execute('SELECT payload,n FROM old_rows WHERE t=? AND k=?', (table, key)).fetchone()
        return (loads(row[0]), row[1]) if row else (None, 0)

    def remap(self, table, identifier):
        row = self.conn.execute('SELECT target_id FROM id_map WHERE t=? AND source_id=?', (table, identifier)).fetchone()
        if not row:
            raise RefreshError('Missing parent identity in ' + table + ': ' + str(identifier))
        return row[0]

    def page(self, table, delete, offset, limit):
        if delete:
            query = ('SELECT o.k,o.payload,o.n FROM old_rows o LEFT JOIN wanted_rows w '
                     'ON o.t=w.t AND o.k=w.k WHERE o.t=? AND w.k IS NULL ORDER BY o.k LIMIT ? OFFSET ?')
        else:
            query = 'SELECT k,payload,n FROM wanted_rows WHERE t=? ORDER BY k LIMIT ? OFFSET ?'
        return [(key, loads(payload), count) for key, payload, count in self.conn.execute(query, (table, limit, offset))]
