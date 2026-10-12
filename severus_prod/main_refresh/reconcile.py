# satvvik: Reconcile original loader output using stable IDs and resumable transactions.
import hashlib
import logging

from model import AUTO_ENTITIES, REFERENCES, SPECS, RefreshError, dumps, loads, qualified, quote

LOG = logging.getLogger('main_refresh')


# satvvik: Save a baseline for detecting edits made outside this refresh.
def capture_existing(conn, database, tables, cache):
    for table in tables:
        cache.conn.execute('DELETE FROM old_rows WHERE t=?', (table.name,))
        cache.conn.execute('DELETE FROM entities WHERE t=?', (table.name,))
        count = 0
        for row, weights in table.rows(conn, database):
            key = table.key(row, weights)
            cache.add('old_rows', table.name, key, row)
            if table.name in AUTO_ENTITIES:
                natural = table.key(row, weights, SPECS[table.name])
                cache.conn.execute('INSERT INTO entities(t,natural_key,identifier) VALUES (?,?,?) '
                                   'ON CONFLICT(t,natural_key) DO UPDATE SET identifier=min(identifier,excluded.identifier)',
                                   (table.name, natural, row['id']))
            count += 1
            if count % 5000 == 0:
                cache.conn.commit()
        cache.conn.commit()
        LOG.info('Saved existing %s: %d rows', table.name, count)
    conn.commit()


# satvvik: Reuse existing entity IDs and remap related records before any production writes.
def prepare_desired(conn, reference, tables, cache):
    cache.conn.execute('DELETE FROM wanted_rows')
    cache.conn.execute('DELETE FROM id_map')
    cache.conn.execute('DELETE FROM progress')
    cache.conn.commit()
    for table in tables:
        next_identifier = table.next_id
        old_max = cache.conn.execute('SELECT max(identifier) FROM entities WHERE t=?', (table.name,)).fetchone()[0]
        next_identifier = max(next_identifier, (old_max or 0) + 1)
        seen = set()
        names = set()
        count = 0
        for row, weights in table.rows(conn, reference):
            for column, parent in REFERENCES.get(table.name, {}).items():
                row[column] = cache.remap(parent, row[column])
            if table.name in AUTO_ENTITIES:
                if table.name == 'dbsources':
                    names.add(row['name'].casefold())
                source_identifier = row['id']
                natural = table.key(row, weights, SPECS[table.name])
                if natural in seen:
                    raise RefreshError('The original loader produced ambiguous duplicate entities in ' + table.name)
                seen.add(natural)
                match = cache.conn.execute('SELECT identifier FROM entities WHERE t=? AND natural_key=?',
                                           (table.name, natural)).fetchone()
                identifier = match[0] if match else next_identifier
                if not match:
                    next_identifier += 1
                row['id'] = identifier
                cache.conn.execute('INSERT INTO id_map(t,source_id,target_id) VALUES (?,?,?)',
                                   (table.name, source_identifier, identifier))
            cache.add('wanted_rows', table.name, table.key(row, weights), row)
            count += 1
            if count % 5000 == 0:
                cache.conn.commit()
        # satvvik: Retain existing source lookup entries that this refresh does not touch.
        if table.name == 'dbsources':
            touched = {row[0] for row in cache.conn.execute('SELECT target_id FROM id_map WHERE t="dbsources"')}
            for key, payload, copies in cache.conn.execute('SELECT k,payload,n FROM old_rows WHERE t="dbsources"'):
                row = loads(payload)
                if row['id'] not in touched and row['name'].casefold() not in names:
                    cache.add('wanted_rows', table.name, key, row, copies)
        cache.conn.commit()
        LOG.info('Prepared refreshed %s: %d source rows', table.name, count)
    conn.commit()


def same_data(table, left, right):
    return all(left[name] == right[name] for name in table.data_columns)


# satvvik: Lock each batch while checking current rows and applying changes.
def current_page(cursor, database, table, page):
    selections, names = table.selections()
    predicates, values = [], []
    for _, row, _ in page:
        where, args = table.where(row)
        predicates.append('(' + where + ')')
        values.extend(args)
    cursor.execute('SELECT ' + ','.join(selections) + ' FROM ' + qualified(database, table.name)
                   + ' WHERE ' + ' OR '.join(predicates) + ' FOR UPDATE', tuple(values))
    grouped = {}
    for result in cursor.fetchall():
        row, weights = table.decode(dict(zip(names, result)))
        grouped.setdefault(table.key(row, weights), []).append(row)
    return grouped


# satvvik: Limit INSERT size while preserving duplicate counts from the original loader output.
def insert_batch(cursor, database, table, records, batch_size):
    columns = table.data_columns
    statement = 'INSERT INTO ' + qualified(database, table.name) + ' (' + ','.join(quote(name) for name in columns)
    statement += ') VALUES (' + ','.join('%s' for _ in columns) + ')'
    values = []
    for row, count in records:
        entry = tuple(row[name] for name in columns)
        while count:
            take = min(count, batch_size - len(values))
            values.extend([entry] * take)
            count -= take
            if len(values) == batch_size:
                cursor.executemany(statement, values)
                if cursor.rowcount != len(values):
                    raise RefreshError('Incomplete insert into ' + table.name)
                values = []
    if values:
        cursor.executemany(statement, values)
        if cursor.rowcount != len(values):
            raise RefreshError('Incomplete final insert into ' + table.name)


# satvvik: Accept already-applied rows on resume and reject changes made by another writer.
def plan_upsert(table, cache, key, desired, count, actual):
    if len(actual) == count and all(same_data(table, row, desired) for row in actual):
        return 'unchanged'
    previous, previous_count = cache.old(table.name, key)
    if previous is None:
        if actual:
            raise RefreshError('A record changed outside this refresh in ' + table.name)
    elif len(actual) != previous_count or any(not same_data(table, row, previous) for row in actual):
        raise RefreshError('A record changed outside this refresh in ' + table.name)
    if table.primary or table.unique:
        if count != 1:
            raise RefreshError('Duplicate rows conflict with an existing key in ' + table.name)
        return 'update' if actual else 'insert'
    return 'replace'


def apply_page(cursor, database, table, cache, page, batch_size, delete):
    grouped = current_page(cursor, database, table, page)
    inserts, changed = [], 0
    for key, row, count in page:
        actual = grouped.get(key, [])
        where, values = table.where(row)
        if delete:
            if not actual:
                continue
            if len(actual) != count or any(not same_data(table, item, row) for item in actual):
                raise RefreshError('A disappearing record changed outside this refresh in ' + table.name)
            action = 'delete'
        else:
            action = plan_upsert(table, cache, key, row, count, actual)
        if action == 'unchanged':
            continue
        if action == 'update':
            columns = table.data_columns
            cursor.execute('UPDATE ' + qualified(database, table.name) + ' SET '
                           + ','.join(quote(name) + '=%s' for name in columns) + ' WHERE ' + where,
                           tuple(row[name] for name in columns) + values)
        elif action == 'delete' or (action == 'replace' and actual):
            cursor.execute('DELETE FROM ' + qualified(database, table.name) + ' WHERE ' + where, values)
        if action in ('insert', 'replace'):
            inserts.append((row, count))
        changed += 1
    insert_batch(cursor, database, table, inserts, batch_size)
    return changed


def merge_table(conn, database, table, cache, batch_size=5000, delete=False, after_commit=None):
    phase = ('delete:' if delete else 'upsert:') + table.name
    offset = cache.offset(phase)
    while True:
        page = cache.page(table.name, delete, offset, batch_size)
        if not page:
            break
        cursor = conn.cursor()
        try:
            changed = apply_page(cursor, database, table, cache, page, batch_size, delete)
            # satvvik: Commit before advancing the checkpoint; replay is safe if saving progress fails.
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            cursor.close()
        if after_commit:
            after_commit(phase, offset)
        offset += len(page)
        cache.advance(phase, offset)
        LOG.info('%s: %d record groups processed, %d changed in this batch', phase, offset, changed)


# satvvik: Check final values and duplicate counts against the completed original-loader output.
def validate_result(conn, database, tables, cache):
    for table in tables:
        cache.conn.execute('DROP TABLE IF EXISTS observed_rows')
        cache.conn.execute('CREATE TEMP TABLE observed_rows (k TEXT PRIMARY KEY,payload TEXT,n INTEGER)')
        for row, weights in table.rows(conn, database):
            key = table.key(row, weights)
            data = {name: row[name] for name in table.data_columns}
            cache.conn.execute('INSERT INTO observed_rows(k,payload,n) VALUES (?,?,1) '
                               'ON CONFLICT(k) DO UPDATE SET n=n+1', (key, dumps(data)))
        for key, payload, count in cache.conn.execute('SELECT k,payload,n FROM wanted_rows WHERE t=?', (table.name,)):
            wanted = loads(payload)
            expected = dumps({name: wanted[name] for name in table.data_columns})
            actual = cache.conn.execute('SELECT payload,n FROM observed_rows WHERE k=?', (key,)).fetchone()
            if not actual or actual != (expected, count):
                raise RefreshError('Final values or duplicate counts differ from the original loader output in ' + table.name)
            cache.conn.execute('DELETE FROM observed_rows WHERE k=?', (key,))
        if cache.conn.execute('SELECT count(*) FROM observed_rows').fetchone()[0]:
            raise RefreshError('Unexpected extra records remain in ' + table.name)
        cache.conn.commit()
    conn.commit()


def schema_signature(conn, database, tables):
    digest = hashlib.sha256()
    cursor = conn.cursor()
    try:
        for table in tables:
            cursor.execute('SHOW CREATE TABLE ' + qualified(database, table.name))
            definition = cursor.fetchone()[1]
            import re
            # satvvik: Ignore the counter when checking that table definitions stayed unchanged.
            definition = re.sub(r' AUTO_INCREMENT=\d+', '', definition)
            digest.update(definition.encode('utf-8'))
    finally:
        cursor.close()
    conn.commit()
    return digest.hexdigest()
