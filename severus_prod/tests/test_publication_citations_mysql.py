import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from unittest.mock import patch

import mysql.connector

SCRIPT = os.environ.get('PUBLICATION_TEST_SCRIPT', '/data/Projects/Hippip/scripts/publication/update.py')
spec = importlib.util.spec_from_file_location('publication_count_update', SCRIPT)
update = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = update
spec.loader.exec_module(update)
SOCKET = os.environ.get('PUBLICATION_TEST_SOCKET', '')
if not re.fullmatch(r'/tmp/hippip-publication-citation-mysql-[^/]+/mysql.sock', SOCKET):
    raise SystemExit('Use the disposable publication citation MySQL runner; production sockets are forbidden')


class Client:
    def __init__(self, links=None, unavailable=(), fail_stage=None):
        self.links = links or {}
        self.unavailable = set(unavailable)
        self.fail_stage = fail_stage
        self.calls = []
        self.stopped = threading.Event()
        self.window = self

    def remaining(self):
        return 1000

    def fetch(self, stage, pmids):
        self.calls.append((stage, list(pmids)))
        if stage == self.fail_stage:
            raise update.UpdateError('fixture API failure')
        if stage == 'citation_counts':
            return update.fetch_verified_citations(self, pmids)
        if stage == 'known_citations':
            return {pmid: self.links.get(pmid, []) for pmid in pmids}
        articles = {pmid: update.Article(pmid, 'New title '+pmid, 'Journal', datetime(2000,1,1),
                                        ('Author One',), 49)
                    for pmid in pmids if pmid not in self.unavailable}
        missing = {pmid: 'UID='+pmid+': cannot get document summary'
                   for pmid in pmids if pmid in self.unavailable}
        return update.ArticleBatch(articles, missing)


class CitationMySQLTests(unittest.TestCase):
    sequence = 0

    def setUp(self):
        type(self).sequence += 1
        self.db = 'publication_citation_fixture_'+str(self.sequence)
        self.admin = mysql.connector.connect(user='root', unix_socket=SOCKET, autocommit=True)
        cursor = self.admin.cursor()
        cursor.execute('CREATE DATABASE '+self.db+' CHARACTER SET utf8mb4')
        cursor.close()
        self.conn = mysql.connector.connect(user='root', unix_socket=SOCKET, database=self.db,
                                            autocommit=False, raise_on_warnings=True)
        cursor = self.conn.cursor()
        cursor.execute('SELECT @@SESSION.sql_mode')
        sql_mode = cursor.fetchone()[0]
        update.set_citation_ddl_mode(cursor, ','.join(mode for mode in sql_mode.split(',')
                                    if mode not in {'NO_ZERO_DATE','NO_ZERO_IN_DATE'}))
        cursor.execute("""CREATE TABLE publications (
            id BIGINT UNSIGNED PRIMARY KEY, title VARCHAR(255) NOT NULL DEFAULT '',
            citation INT UNSIGNED NOT NULL DEFAULT 0, citation5 INT UNSIGNED NOT NULL DEFAULT 0,
            pubdate TIMESTAMP NOT NULL DEFAULT '0000-00-00 00:00:00', journal VARCHAR(255) NOT NULL DEFAULT '',
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB""")
        update.set_citation_ddl_mode(cursor, sql_mode)
        cursor.execute('CREATE TABLE publication2publications (cited_id BIGINT UNSIGNED, citing_id BIGINT UNSIGNED, PRIMARY KEY(cited_id,citing_id)) ENGINE=InnoDB')
        cursor.execute('CREATE TABLE publication2authors (publication_id BIGINT UNSIGNED, author VARCHAR(255), PRIMARY KEY(publication_id,author)) ENGINE=InnoDB')
        cursor.execute('CREATE TABLE valid_direct_interactions (id INT PRIMARY KEY) ENGINE=InnoDB')
        cursor.execute('CREATE TABLE interaction2externals (interaction_id INT, dbsource_id INT, external_id VARCHAR(255)) ENGINE=InnoDB')
        cursor.execute('CREATE TABLE interaction2publications (dbsource_id INT, external_id VARCHAR(255), pmid BIGINT UNSIGNED) ENGINE=InnoDB')
        cursor.close()
        self.conn.commit()
        self.temp = tempfile.TemporaryDirectory(prefix='publication-count-checkpoint-')
        self.checkpoint = update.Checkpoint(Path(self.temp.name)/'all.json')
        self.identity = {'host':'fixture', 'port':3306, 'database':self.db}

    def tearDown(self):
        self.conn.close()
        cursor = self.admin.cursor()
        cursor.execute('DROP DATABASE '+self.db)
        cursor.close()
        self.admin.close()
        self.temp.cleanup()

    def seed(self, pmid='100', count=49):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO publications(id,title,citation,citation5,pubdate,journal) VALUES(%s,'Old title',%s,5,'2000-01-01','Old journal')", (pmid,count))
        cursor.close()
        self.conn.commit()

    def known(self, pmids=('100',)):
        cursor = self.conn.cursor()
        for index, pmid in enumerate(pmids,1):
            cursor.execute('INSERT INTO valid_direct_interactions VALUES(%s)', (index,))
            cursor.execute('INSERT INTO interaction2externals VALUES(%s,1,%s)', (index,str(index)))
            cursor.execute('INSERT INTO interaction2publications VALUES(1,%s,%s)', (str(index),pmid))
        cursor.close()
        self.conn.commit()

    def row(self, pmid='100'):
        cursor = self.conn.cursor()
        cursor.execute('SELECT citation,citation_source,citation_checked_at,citation5,title FROM publications WHERE id=%s', (pmid,))
        row = cursor.fetchone()
        cursor.close()
        self.conn.commit()
        return row

    def links(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT cited_id,citing_id FROM publication2publications ORDER BY cited_id,citing_id')
        rows = cursor.fetchall()
        cursor.close()
        self.conn.commit()
        return rows

    def prepare(self):
        update.prepare_citation_schema(self.conn)

    def runner(self, client, stages=update.STAGES, workers=2, batch=20):
        return update.Runner(self.conn, client, self.checkpoint, self.identity, stages,
                             summary_batch=batch, citation_batch=batch, workers=workers)

    def test_migration_marks_old_refcounts_unknown_and_keeps_other_data(self):
        self.seed()
        self.prepare()
        row = self.row()
        self.assertEqual(row,(None,None,None,5,'Old title'))
        cursor = self.conn.cursor()
        cursor.execute("SELECT IS_NULLABLE,COLUMN_DEFAULT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='publications' AND COLUMN_NAME='citation'")
        self.assertEqual(cursor.fetchone(),('YES',None))
        cursor.execute('SELECT @@SESSION.sql_mode')
        self.assertIn('NO_ZERO_DATE',cursor.fetchone()[0])
        cursor.close()

    def test_migration_is_idempotent_and_preserves_verified_counts(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200']})
        before = self.row()
        self.prepare()
        self.assertEqual(self.row(),before)

    def test_metadata_does_not_overwrite_verified_count(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200','300']})
        before = self.row()
        update.commit_batch(self.conn,'known_articles',Client().fetch('known_articles',['100']))
        after = self.row()
        self.assertEqual(after[:4],before[:4])
        self.assertEqual(after[4],'New title 100')

    def test_new_metadata_has_unknown_count_instead_of_refcount(self):
        self.prepare()
        update.commit_batch(self.conn,'known_articles',Client().fetch('known_articles',['100']))
        self.assertEqual(self.row()[:3],(None,None,None))

    def test_duplicates_count_once_and_links_are_replaced_together(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200','200','300']})
        self.assertEqual(self.row()[0],2)
        self.assertEqual(self.row()[1],update.CITATION_SOURCE)
        self.assertIsNotNone(self.row()[2])
        self.assertEqual(self.links(),[(100,200),(100,300)])
        update.commit_batch(self.conn,'known_citations',{'100':['400']})
        self.assertEqual(self.row()[0],1)
        self.assertEqual(self.links(),[(100,400)])

    def test_valid_empty_result_sets_verified_zero_and_clears_links(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200']})
        update.commit_batch(self.conn,'known_citations',{'100':[]})
        self.assertEqual(self.row()[0],0)
        self.assertEqual(self.row()[1],update.CITATION_SOURCE)
        self.assertIsNotNone(self.row()[2])
        self.assertEqual(self.links(),[])

    def test_count_write_failure_rolls_back_link_deletes_and_counts(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200']})
        before = self.row()
        with patch.object(update,'write_citation_counts',side_effect=RuntimeError('count write failed')):
            with self.assertRaisesRegex(RuntimeError,'count write failed'):
                update.commit_batch(self.conn,'known_citations',{'100':['300']})
        self.assertEqual(self.links(),[(100,200)])
        self.assertEqual(self.row(),before)

    def test_real_constraint_failure_rolls_back_whole_batch(self):
        self.seed('100');self.seed('101');self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200'],'101':['201']})
        before = [self.row('100'),self.row('101')]
        with patch.object(update,'write_citation_counts',wraps=update.write_citation_counts) as writer:
            cursor = self.conn.cursor()
            cursor.execute("CREATE TRIGGER refuse_citation BEFORE UPDATE ON publications FOR EACH ROW BEGIN IF NEW.id=101 AND NEW.citation=2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='fixture count failure'; END IF; END")
            cursor.close()
            with self.assertRaises(mysql.connector.Error):
                update.commit_batch(self.conn,'known_citations',{'100':['300'],'101':['301','302']})
            self.assertTrue(writer.called)
        self.assertEqual(self.links(),[(100,200),(101,201)])
        self.assertEqual([self.row('100'),self.row('101')],before)

    def test_missing_metadata_is_an_error_and_links_rollback(self):
        self.prepare()
        with self.assertRaisesRegex(update.UpdateError,'Missing metadata'):
            update.commit_batch(self.conn,'known_citations',{'100':['200']})
        self.assertEqual(self.links(),[])

    def test_counts_only_pass_does_not_expand_links_or_article_graph(self):
        self.seed('999');self.known();self.prepare()
        client = Client({'100':['200','300'],'200':['400'],'300':[],'999':['500','600']})
        self.runner(client).run()
        self.assertEqual(self.links(),[(100,200),(100,300)])
        self.assertEqual([self.row(pmid)[0] for pmid in ['100','200','300','999']],[2,1,0,2])
        self.assertIsNone(self.row('400'))
        self.assertIsNone(self.row('500'))
        self.assertFalse(any(stage=='citation_counts' and '100' in ids for stage,ids in client.calls))
        self.assertTrue(self.checkpoint.load()['completed'])

    def test_invalid_known_pmid_preserves_links_and_has_unknown_count(self):
        self.seed('100');self.known();self.prepare()
        cursor=self.conn.cursor();cursor.execute('INSERT INTO publication2publications VALUES(100,200)');cursor.close();self.conn.commit()
        client=Client({'100':[]},unavailable={'100'})
        self.runner(client).run()
        self.assertEqual(self.row()[:3],(None,None,None))
        self.assertEqual(self.links(),[(100,200)])
        self.assertFalse(any(stage=='known_citations' and '100' in ids for stage,ids in client.calls))
        self.assertIn('100',self.checkpoint.load()['unavailable_articles'])

    def test_invalid_extra_pmid_is_not_misreported_as_zero(self):
        self.seed();self.prepare()
        client=Client(unavailable={'100'})
        self.runner(client,stages=('citation_counts',)).run()
        self.assertEqual(self.row()[:3],(None,None,None))
        self.assertFalse(any(stage=='known_citations' for stage,_ in client.calls))
        self.assertEqual(self.checkpoint.load()['unavailable_articles']['100']['stage'],'citation_counts')

    def test_unavailable_pmid_preserves_previously_verified_count(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200']})
        before=self.row()
        self.runner(Client(unavailable={'100'}),stages=('citation_counts',)).run()
        self.assertEqual(self.row(),before)
        self.assertEqual(self.links(),[(100,200)])

    def test_failed_api_preserves_counts_and_does_not_advance_checkpoint(self):
        self.seed();self.prepare()
        update.commit_batch(self.conn,'known_citations',{'100':['200']})
        before=self.row()
        with self.assertRaisesRegex(update.UpdateError,'fixture API failure'):
            self.runner(Client(fail_stage='known_citations'),stages=('citation_counts',)).run()
        self.assertEqual(self.row(),before)
        self.assertEqual(self.checkpoint.load()['work']['next_index'],0)
        self.assertEqual(self.links(),[(100,200)])

    def test_resume_after_commit_before_checkpoint_save_is_idempotent(self):
        self.seed();self.known();self.prepare()
        client=Client({'100':['200']})
        real_save=self.checkpoint.save
        raised=False
        def save(state):
            nonlocal raised
            if not raised and state['stage_index']==1 and state['work'] and state['work']['next_index']==1:
                raised=True
                raise OSError('fixture checkpoint failure')
            real_save(state)
        with patch.object(self.checkpoint,'save',side_effect=save):
            with self.assertRaisesRegex(OSError,'fixture checkpoint failure'):
                self.runner(client,workers=1).run()
        self.assertEqual(self.row()[0],1)
        self.assertEqual(self.links(),[(100,200)])
        self.runner(Client({'100':['200']}),workers=1).run()
        self.assertEqual(self.links(),[(100,200)])
        self.assertEqual(self.row()[0],1)
        self.assertTrue(self.checkpoint.load()['completed'])

    def test_legacy_checkpoint_replays_counts_without_restarting_metadata(self):
        self.seed('100');self.seed('200');self.known();self.prepare()
        self.checkpoint.save_worklist('known',['100'])
        self.checkpoint.save_worklist('citing',['200'])
        self.checkpoint.save({'version':1,'identity':self.identity,'stages':list(update.LEGACY_STAGES),
            'stage_index':2,'known_loaded':True,'work':{'list':'citing','next_index':1},'completed':False})
        client=Client({'100':['200'],'200':['300']})
        self.runner(client).run()
        self.assertEqual(self.row('100')[0],1)
        self.assertEqual(self.row('200')[0],1)
        self.assertNotIn(('known_articles',['100']),client.calls)
        self.assertEqual(self.checkpoint.load()['version'],2)
        self.assertTrue(self.checkpoint.load()['completed'])

    def test_legacy_metadata_checkpoint_keeps_offset_but_refreshes_all_counts(self):
        self.seed('100');self.known(('100','101'));self.prepare()
        self.checkpoint.save_worklist('known',['100','101'])
        self.checkpoint.save({'version':1,'identity':self.identity,'stages':list(update.LEGACY_STAGES),
            'stage_index':0,'known_loaded':True,'work':{'list':'known','next_index':1},'completed':False})
        client=Client({'100':[],'101':[]})
        self.runner(client,workers=1,batch=1).run()
        self.assertNotIn(('known_articles',['100']),client.calls)
        self.assertIn(('known_articles',['101']),client.calls)
        self.assertEqual(self.row('100')[0],0)
        self.assertEqual(self.row('101')[0],0)

    def test_standalone_known_citations_validates_metadata_and_skips_invalid_sources(self):
        self.known(('100','101'));self.prepare()
        client=Client({'100':['200']},unavailable={'101'})
        self.runner(client,stages=('known_citations',)).run()
        self.assertEqual(self.row('100')[0],1)
        self.assertIsNone(self.row('101'))
        self.assertEqual(self.links(),[(100,200)])
        self.assertFalse(any(stage=='known_citations' and '101' in ids for stage,ids in client.calls))

    def test_empty_database_completes_without_api_calls(self):
        self.prepare();client=Client()
        self.runner(client).run()
        self.assertEqual(client.calls,[])
        self.assertTrue(self.checkpoint.load()['completed'])

    def test_migration_preserves_existing_zero_pubdate(self):
        cursor=self.conn.cursor()
        cursor.execute('SELECT @@SESSION.sql_mode');original=cursor.fetchone()[0]
        update.set_citation_ddl_mode(cursor,','.join(mode for mode in original.split(',')
                                    if mode not in {'NO_ZERO_DATE','NO_ZERO_IN_DATE'}))
        cursor.execute("INSERT INTO publications(id,citation,pubdate) VALUES(100,49,'0000-00-00 00:00:00')")
        update.set_citation_ddl_mode(cursor,original)
        cursor.close();self.conn.commit()
        self.prepare()
        self.assertEqual(self.row()[0],None)
        cursor=self.conn.cursor()
        cursor.execute('SELECT CAST(pubdate AS CHAR) FROM publications WHERE id=100')
        self.assertEqual(cursor.fetchone()[0],'0000-00-00 00:00:00')
        cursor.close()

    def test_fresh_schema_template_preserves_old_column_positions(self):
        import warnings
        template=Path(os.environ.get('PUBLICATION_SCHEMA_TEMPLATE','/data/Projects/Hippip/config/dbstructure.sql')).read_text()
        statement=re.search(r'CREATE TABLE IF NOT EXISTS `publications` \(.*?\) ENGINE=InnoDB[^;]*;',template,re.S).group()
        cursor=self.conn.cursor()
        cursor.execute('SELECT @@SESSION.sql_mode');original=cursor.fetchone()[0]
        update.set_citation_ddl_mode(cursor,','.join(mode for mode in original.split(',')
                                    if mode not in {'NO_ZERO_DATE','NO_ZERO_IN_DATE'}))
        cursor.execute('DROP TABLE publications')
        raised=self.conn.raise_on_warnings
        self.conn.raise_on_warnings=False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                cursor.execute(statement)
        finally:
            self.conn.raise_on_warnings=raised
            update.set_citation_ddl_mode(cursor,original)
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='publications' ORDER BY ORDINAL_POSITION")
        self.assertEqual([row[0] for row in cursor.fetchall()],['id','title','citation','citation5','pubdate','journal','updated_at','citation_source','citation_checked_at'])
        cursor.close();self.conn.commit()
        self.prepare()
        update.commit_batch(self.conn,'known_articles',Client().fetch('known_articles',['100']))
        self.assertEqual(self.row()[:3],(None,None,None))

    def test_check_config_does_not_migrate_or_change_legacy_counts(self):
        self.seed()
        env={'DB_PASS':'', 'NCBI_API_KEY':'fixture-key'}
        with patch.dict(os.environ,env), patch.object(update.logging,'basicConfig'), \
             patch.object(update.mysql.connector,'connect',return_value=self.conn), \
             patch.object(update,'prepare_citation_schema',side_effect=AssertionError('check-config must not write')), \
             patch.object(update.ApiClient,'fetch',side_effect=AssertionError('check-config must not call NCBI')):
            status=update.cli(argv=['--database',self.db,'--username','root','--state-dir',self.temp.name,'--check-config'])
        self.assertEqual(status,0)
        self.conn=mysql.connector.connect(user='root',unix_socket=SOCKET,database=self.db,
                                          autocommit=False,raise_on_warnings=True)
        cursor=self.conn.cursor()
        cursor.execute('SELECT citation FROM publications WHERE id=100')
        self.assertEqual(cursor.fetchone()[0],49)
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='publications'")
        self.assertNotIn('citation_source',{row[0] for row in cursor.fetchall()})
        cursor.close()

    def test_schema_changes_can_resume_after_legacy_count_clear_failure(self):
        self.seed()
        real_cursor=self.conn.cursor
        class FailingCursor:
            def __init__(self): self.cursor=real_cursor()
            def __getattr__(self,name): return getattr(self.cursor,name)
            def execute(self,query,params=()):
                if 'UPDATE publications SET citation=NULL' in query:
                    raise RuntimeError('fixture interruption after DDL')
                return self.cursor.execute(query,params)
        with patch.object(self.conn,'cursor',side_effect=FailingCursor):
            with self.assertRaisesRegex(RuntimeError,'interruption after DDL'):
                self.prepare()
        self.assertEqual(self.row()[0],49)
        self.prepare()
        self.assertEqual(self.row()[:3],(None,None,None))

    def test_original_session_mode_is_restored_after_failed_alter(self):
        self.seed()
        cursor=self.conn.cursor();cursor.execute('SELECT @@SESSION.sql_mode');before=cursor.fetchone()[0];cursor.close()
        real_cursor=self.conn.cursor
        class FailingCursor:
            def __init__(self): self.cursor=real_cursor()
            def __getattr__(self,name): return getattr(self.cursor,name)
            def execute(self,query,params=()):
                if query.startswith('ALTER TABLE publications'):
                    raise RuntimeError('fixture DDL failure')
                return self.cursor.execute(query,params)
        with patch.object(self.conn,'cursor',side_effect=FailingCursor):
            with self.assertRaisesRegex(RuntimeError,'DDL failure'):
                self.prepare()
        cursor=self.conn.cursor();cursor.execute('SELECT @@SESSION.sql_mode');after=cursor.fetchone()[0];cursor.close()
        self.assertEqual(after,before)

    def test_counts_only_resume_keeps_committed_offset(self):
        for pmid in ['100','101','102']: self.seed(pmid)
        self.prepare()
        client=Client({'100':['200'],'101':['201'],'102':[]})
        real_save=self.checkpoint.save
        raised=False
        def save(state):
            nonlocal raised
            if not raised and state['work'] and state['work']['next_index']==2:
                raised=True
                raise OSError('fixture counts checkpoint failure')
            real_save(state)
        with patch.object(self.checkpoint,'save',side_effect=save):
            with self.assertRaises(OSError):
                self.runner(client,stages=('citation_counts',),workers=1,batch=1).run()
        self.assertEqual(self.checkpoint.load()['work']['next_index'],1)
        new_client=Client({'100':['200'],'101':['201'],'102':[]})
        self.runner(new_client,stages=('citation_counts',),workers=1,batch=1).run()
        self.assertFalse(any('100' in ids for _,ids in new_client.calls))
        self.assertEqual([self.row(pmid)[0] for pmid in ['100','101','102']],[1,1,0])
        self.assertTrue(self.checkpoint.load()['completed'])

    def test_completed_checkpoint_starts_a_fresh_count_refresh(self):
        self.seed();self.known();self.prepare()
        self.runner(Client({'100':['200']})).run()
        self.runner(Client({'100':[]})).run()
        self.assertEqual(self.row()[0],0)
        self.assertEqual(self.links(),[])


if __name__=='__main__':
    unittest.main(verbosity=2)
