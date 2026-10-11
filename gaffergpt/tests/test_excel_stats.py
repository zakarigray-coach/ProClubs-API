import json
import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.weekly_intake import save_submission
from gaffergpt.excel_stats import imported_statistics,save_excel_statistics,player_totals
from gaffergpt.reporter import Reporter

class ExcelStatsTests(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory();self.db=Database(Path(self.root.name)/'pep.db')
        self.rid=self.db.open_report('2026-10-05T04:00:00+00:00','2026-10-12T04:00:00+00:00',1)['report_id']
        self.source=json.dumps({'worksheets':[{'sheet':'Matches','rows':[['Date','Match ID','Goals for','Goals against','Opponent','Shots','Pass %'],['2026-10-07T02:00:00+00:00','source-a',2,1,'Chelsea',5,0.75],['2026-10-07T02:30:00+00:00','source-b',1,3,'Chelsea',3,0.5]]},{'sheet':'Player matches','rows':[['Match ID','Player','Rating','Goals','Assists','Passes made','Pass attempts','Saves','Seconds played'],['source-a','Zak',8.5,1,1,15,20,None,5400],['source-b','Zak',6.5,0,1,2,10,None,5400],['source-a','Keeper',7.5,0,0,5,5,4,5400],['source-a','Unused',3,0,0,0,0,0,0]]}]})
        save_submission(self.db,self.rid,1,2,'2026-10-06 | Official Home | Chelsea | 2-1\n2026-10-06 | Practice | Chelsea | 1-3')
        self.matches=self.db.rows('SELECT * FROM matches ORDER BY match_id')
    def tearDown(self):self.root.cleanup()
    def test_exact_mapping_and_selected_only_stats(self):
        stats=imported_statistics(self.source,self.matches)
        self.assertTrue(stats)
        save_excel_statistics(self.db,self.source,self.matches)
        rows=self.db.rows('SELECT * FROM match_statistics')
        zak=next(p for p in player_totals(rows) if p['player']=='Zak')
        self.assertEqual(zak['goals'],1);self.assertEqual(zak['assists'],2)
        self.assertAlmostEqual(zak['average_rating'],7.5)
        self.assertAlmostEqual(zak['pass_accuracy'],100*17/30)
        self.assertNotIn('saves',zak)
        self.assertNotIn('Unused',[p['player'] for p in player_totals(rows)])
        mid=self.matches[0]['match_id']
        self.db.replace_page_selection(self.rid,[m['match_id'] for m in self.matches],[mid]);self.db.confirm_report(self.rid)
        article=Reporter(self.db).generate(self.rid)
        self.assertIn('Zak: 1 appearances, 1 goals, 1 assists',article)
        self.assertIn('8.50 average rating',article)
        self.assertNotIn('6.50',article)
        self.assertNotIn('PRACTICE PLAYER PERFORMANCES',article)
        before=len(self.db.rows('SELECT * FROM match_statistics'))
        save_excel_statistics(self.db,self.source,self.matches)
        self.assertEqual(len(self.db.rows('SELECT * FROM match_statistics')),before)
    def test_ambiguous_or_mismatched_game_does_not_receive_stats(self):
        changed=[{**self.matches[0],'opponent':'Arsenal'}]
        self.assertEqual(imported_statistics(self.source,changed),[])
