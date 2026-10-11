import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.weekly_intake import save_submission
from gaffergpt.reporter import Reporter
from gaffergpt.article_writer import SportsWriter, editorial_packet

class SportsArticleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'db.sqlite')
        self.rid=self.db.open_report('2026-10-05T04:00:00+00:00','2026-10-12T04:00:00+00:00','1')['report_id']
        save_submission(self.db,self.rid,'1','guild','2026-10-06 | Practice | Chelsea | 2-1\n2026-10-07 | Practice | Arsenal | 0-3')
        ids=[r['match_id'] for r in self.db.rows('SELECT match_id FROM matches')]
        self.db.replace_page_selection(self.rid,ids,ids[:1]);self.db.confirm_report(self.rid)
    def tearDown(self):self.tmp.cleanup()
    def test_writer_gets_only_selected_facts_and_readable_dates(self):
        class Writer:
            def write(inner,packet):
                self.assertEqual(len(packet['matches']),1)
                self.assertEqual(packet['matches'][0]['opponent'],'Chelsea')
                self.assertNotIn('match_id',packet['matches'][0])
                self.assertIn('October 5',packet['period'])
                return 'Blues find a training-ground lift','Birmingham beat Chelsea 2–1 in practice.'
        article=Reporter(self.db,writer=Writer()).generate(self.rid)
        self.assertIn('Blues find a training-ground lift',article)
        self.assertNotIn('PLAYER STATS',article)
        self.assertNotIn('end exclusive',article)
        self.assertEqual(self.db.report(self.rid)['status'],'draft')
    def test_provider_failure_preserves_confirmed_report_for_retry(self):
        class Writer:
            def write(self,packet):raise RuntimeError('provider unavailable')
        with self.assertRaises(RuntimeError):Reporter(self.db,writer=Writer()).generate(self.rid)
        self.assertEqual(self.db.report(self.rid)['status'],'confirmed')
        self.assertFalse(self.db.report(self.rid)['article'])
    def test_provider_uses_structured_article_output(self):
        payload=SportsWriter('test').payload('{}')
        self.assertEqual(payload['text']['format']['schema']['required'],['title','body'])
        self.assertIn('500–750',payload['instructions'])

    def test_legacy_outfield_conceded_stats_never_reach_writer(self):
        packet={'observations':{'player_statistics':{'Practice':[
            {'player':'Outfield','appearances':4,'goals_conceded':10,'clean_sheets':1,'metric_samples':{'goals_conceded':4}},
            {'player':'Keeper','appearances':2,'goalkeeper_appearances':2,'goals_conceded':3}]}}}
        clean=editorial_packet(packet)['observations']['player_statistics']['Practice']
        self.assertNotIn('goals_conceded',clean[0])
        self.assertNotIn('clean_sheets',clean[0])
        self.assertEqual(clean[1]['goals_conceded'],3)
        self.assertEqual(packet['observations']['player_statistics']['Practice'][0]['goals_conceded'],10)
