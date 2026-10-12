import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

SCRIPT = os.environ.get('PUBLICATION_TEST_SCRIPT', '/data/Projects/Hippip/scripts/publication/update.py')
spec = importlib.util.spec_from_file_location('publication_citation_test', SCRIPT)
update = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = update
spec.loader.exec_module(update)
ROOT = Path(os.environ.get('PUBLICATION_LAUNCHER_ROOT', str(Path(__file__).resolve().parents[1])))
DATABASES = ('db_pred','db_published','db_k_graph')


def summary(pmids=('100',), unavailable=()):
    return ('<eSummaryResult>'+''.join(
        '<ERROR>UID='+pmid+': cannot get document summary</ERROR>' if pmid in unavailable else
        '<DocSum><Id>'+pmid+'</Id><Item Name="Title">Example paper</Item>'
        '<Item Name="FullJournalName">Example journal</Item><Item Name="PmcRefCount">49</Item>'
        '<Item Name="History"><Item Name="pubmed">2000/01/01 00:00</Item></Item></DocSum>'
        for pmid in pmids)+'</eSummaryResult>').encode()


def links(mapping):
    return ('<eLinkResult>'+''.join(
        '<LinkSet><DbFrom>pubmed</DbFrom><IdList><Id>'+source+'</Id></IdList>'+
        ('<LinkSetDb><DbTo>pubmed</DbTo><LinkName>pubmed_pubmed_citedin</LinkName>'+''.join(
            '<Link><Id>'+pmid+'</Id></Link>' for pmid in citing)+'</LinkSetDb>' if citing else '')+
        '</LinkSet>' for source,citing in mapping.items())+'</eLinkResult>').encode()


class Window:
    def remaining(self):
        return 1000


class Limiter:
    def __init__(self):
        self.calls=0

    def acquire(self,*args):
        self.calls+=1
        return 1000


class ParserAndAPITests(unittest.TestCase):
    def test_reference_count_is_retained_only_as_reference_metadata(self):
        article=update.parse_articles(summary(),['100'])['100']
        self.assertEqual(article.refcount,49)
        self.assertEqual(article.title,'Example paper')

    def test_incoming_links_are_deduplicated_per_requested_paper(self):
        result=update.parse_citations(links({'100':['300','200','200'],'101':[]}),['100','101'])
        self.assertEqual(result,{'100':['200','300'],'101':[]})

    def test_outgoing_reference_links_are_rejected(self):
        payload=links({'100':['200']}).replace(b'pubmed_pubmed_citedin',b'pubmed_pubmed_refs')
        with self.assertRaisesRegex(update.ResponseError,'unexpected link type'):
            update.parse_citations(payload,['100'])

    def test_generic_api_error_is_never_a_zero_count(self):
        for payload in [b'<eLinkResult><ERROR>server failure</ERROR></eLinkResult>',b'{"error":"rate exceeded"}']:
            with self.assertRaises(update.ResponseError):
                update.parse_citations(payload,['100'])

    def test_missing_source_or_merged_source_results_are_rejected(self):
        with self.assertRaisesRegex(update.ResponseError,'omitted requested PMIDs'):
            update.parse_citations(links({'100':[]}),['100','101'])
        payload=links({'100':['200']}).replace(b'<Id>100</Id>',b'<Id>100</Id><Id>101</Id>',1)
        with self.assertRaisesRegex(update.ResponseError,'one result per requested PMID'):
            update.parse_citations(payload,['100','101'])

    def test_counts_only_requests_validate_sources_before_counting_and_use_post(self):
        requests=[];limiter=Limiter()
        def opener(request,timeout):
            params=urllib.parse.parse_qs(request.data.decode())
            requests.append((request.full_url,request.method,params))
            payload=summary(('100','101'),{'101'}) if 'esummary' in request.full_url else links({'100':['200','200']})
            return contextlib.closing(io.BytesIO(payload))
        client=update.ApiClient('fixture-key','fixture@example.org','fixture',Window(),
                               limiter=limiter,opener=opener,attempts=1)
        result=client.fetch('citation_counts',['100','101'])
        self.assertEqual(dict(result),{'100':['200']})
        self.assertIn('101',result.unavailable)
        self.assertEqual(limiter.calls,2)
        self.assertEqual([request[1] for request in requests],['POST','POST'])
        self.assertEqual(requests[1][2]['id'],['100'])
        self.assertEqual(requests[1][2]['linkname'],['pubmed_pubmed_citedin'])

    def test_elink_batch_uses_separate_id_fields(self):
        requests=[]
        def opener(request,timeout):
            requests.append(urllib.parse.parse_qs(request.data.decode()))
            return contextlib.closing(io.BytesIO(links({'100':[],'101':[]})))
        client=update.ApiClient('fixture-key','fixture@example.org','fixture',Window(),
                               limiter=Limiter(),opener=opener,attempts=1)
        self.assertEqual(client.fetch('known_citations',['100','101']),{'100':[],'101':[]})
        self.assertEqual(requests[0]['id'],['100','101'])

    def test_default_workers_rate_and_new_stage(self):
        args=update.argument_parser().parse_args([])
        self.assertEqual((args.workers,args.rate,args.citation_batch_size),(4,8,20))
        self.assertEqual(update.argument_parser().parse_args(['--stage','citation_counts']).stage,'citation_counts')

    def test_checkpoint_supports_counts_worklist_and_rejects_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint=update.Checkpoint(Path(folder)/'fixture.json')
            checkpoint.save_worklist('counts',['100','101'])
            self.assertEqual(checkpoint.load_worklist('counts'),['100','101'])
            with self.assertRaises(update.UpdateError):
                checkpoint.worklist_path('../other')


STUB = r'''import json,os,sys
from pathlib import Path
if '--help' in sys.argv:
    print('fixture help')
    raise SystemExit(0)
with Path(os.environ['MOCK_TRACE']).open('a') as handle:
    handle.write(json.dumps({'database':os.environ.get('PRODUCTION_DB'),'state':os.environ.get('PUBLICATION_STATE_DIR'),
        'key_file':os.environ.get('NCBI_API_KEY_FILE'),'args':sys.argv[1:],
        'password_in_environment':'DB_PASS' in os.environ})+'\n')
print('fixture publication output')
print('fixture warning',file=sys.stderr)
raise SystemExit(int(os.environ.get('MOCK_STATUS','0')))
'''


class LogLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='publication-log-launcher-')
        self.base=Path(self.temp.name)
        self.workflow=self.base/'workflows'
        for database in DATABASES:
            target=self.workflow/database/'2_publications.sh'
            target.parent.mkdir(parents=True)
            target.write_text((ROOT/database/'2_publications.sh').read_text())
        self.calculator=self.base/'calculator';self.calculator.mkdir()
        (self.calculator/'update.py').write_text(STUB)
        self.trace=self.base/'trace.jsonl'
        self.env=dict(os.environ,PUBLICATION_SCRIPT=str(self.calculator),PYTHON=sys.executable,
                      MOCK_TRACE=str(self.trace),DB_USER='fixture_user',DB_PASS='fixture_password',
                      PUBLICATION_EMAIL_NOTICES='0')
        for name in ['PUBLICATION_STATE_DIR','PUBLICATION_LOG_DIR','NCBI_API_KEY','NCBI_API_KEY_FILE','PRODUCTION_DB','MOCK_STATUS']:
            self.env.pop(name,None)

    def tearDown(self):
        self.temp.cleanup()

    def run_stage(self,database,args=(),extra=None):
        env=self.env.copy()
        if extra:env.update(extra)
        result=subprocess.run(['bash',str(self.workflow/database/'2_publications.sh'),*args],
                              env=env,cwd=self.base,input='fixture_kgraph\n' if database=='db_k_graph' else '\n',
                              capture_output=True,text=True,timeout=10)
        self.assertNotIn('fixture_password',result.stdout+result.stderr)
        records=[json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []
        return result,records

    def assert_log(self,database,result,folder=None):
        folder=folder or self.workflow/database/'publication_state/logs'
        logs=list(folder.glob('publications-*.log'))
        self.assertEqual(len(logs),1,result.stdout+result.stderr)
        self.assertEqual(logs[0].stat().st_mode & 0o777,0o600)
        self.assertIn('fixture publication output',logs[0].read_text())
        self.assertIn('fixture warning',logs[0].read_text())
        self.assertIn(str(logs[0]),result.stdout)

    def test_each_workflow_keeps_its_own_log_and_shared_checkpoint_default(self):
        for database in DATABASES:
            result,records=self.run_stage(database)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assert_log(database,result)
            record=records[-1]
            self.assertEqual(record['state'],str(self.workflow/'publication_state'))
            self.assertEqual(record['key_file'],str(self.workflow/'.ncbi_api_key'))
            self.assertTrue(record['password_in_environment'])
            self.assertFalse((self.workflow/'publication_state/logs').exists())

    def test_custom_state_directory_does_not_move_workflow_logs(self):
        for database in DATABASES:
            result,records=self.run_stage(database,extra={'PUBLICATION_STATE_DIR':str(self.base/'custom-state')})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assert_log(database,result)
            self.assertEqual(records[-1]['state'],str(self.base/'custom-state'))
            self.assertFalse((self.base/'custom-state/logs').exists())

    def test_failure_status_and_output_are_logged_in_workflow_directory(self):
        for database in DATABASES:
            result,records=self.run_stage(database,extra={'MOCK_STATUS':'9'})
            self.assertEqual(result.returncode,9)
            self.assert_log(database,result)

    def test_postponement_status_is_preserved(self):
        result,_=self.run_stage('db_pred',extra={'MOCK_STATUS':'75'})
        self.assertEqual(result.returncode,75)
        self.assert_log('db_pred',result)

    def test_check_config_is_logged_and_forwarded(self):
        result,records=self.run_stage('db_published',args=('--check-config',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(records[-1]['args'],['--check-config'])
        self.assertIn('configuration check succeeded',result.stdout)
        self.assert_log('db_published',result)

    def test_help_creates_no_log_or_checkpoint(self):
        for database in DATABASES:
            result,records=self.run_stage(database,args=('--help',))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(records,[])
            self.assertFalse((self.workflow/database/'publication_state').exists())

    def test_explicit_log_directory_override(self):
        folder=self.base/'chosen-logs'
        result,_=self.run_stage('db_k_graph',extra={'PUBLICATION_LOG_DIR':str(folder)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assert_log('db_k_graph',result,folder=folder)


if __name__=='__main__':
    unittest.main(verbosity=2)
