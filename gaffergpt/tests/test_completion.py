import io
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.parser import parse_recap
from gaffergpt.reporter import Reporter
from gaffergpt.notebook import daily_backup,notebook

class CompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'pep.db')
    def tearDown(self):
        self.tmp.cleanup()
    def match(self,message,kind='Practice'):
        text='MPL Birmingham 2-1 Chelsea'
        mid=self.db.ingest(message,20,30,'2026-10-06T22:00:00+00:00',text,parse_recap(text))[0]
        self.db.classify(mid,kind,'Home',42)
        return mid
    def draft(self):
        mid=self.match('1');rid=self.db.open_report('2026-10-05','2026-10-12',42)['report_id']
        self.db.replace_page_selection(rid,[mid],[mid]);self.db.confirm_report(rid)
        Reporter(self.db).generate(rid);return rid,mid
    def test_team_stats_are_read_without_inventing_percentages(self):
        text='MPL Birmingham 1-3 Amadness FC\nTEAM STATS\nPASSING — DIRECTION\nBackwards: 20\nSideways: 18\nForwards: 59\nPASSING — LENGTH\nShort: 51\nMedium: 33\nLong: 12\nPOSSESSION WON\nDefensive Third: 3\nMidfield Third: 4\nSHOOTING\nOn Target Inside Box: 4\nPossession: 55%\nFINAL SCORE'
        stats={s['metric']:s for s in parse_recap(text)[0]['statistics']}
        self.assertEqual(stats['passes_forwards']['value'],59)
        self.assertEqual(stats['possession_won_midfield_third']['value'],4)
        self.assertEqual(stats['shots_on_target_inside_box']['value'],4)
        self.assertEqual(stats['possession']['unit'],'%')
        self.assertNotIn('pass_accuracy',stats)
        self.assertNotIn('shots',stats)

    def test_notebook_tables_and_formula_safety(self):
        self.match('1');self.db.link_player(42,'coach','=HYPERLINK("x")',42)
        data=notebook(self.db)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('Peps_Notebook_Matches.csv',z.namelist())
            self.assertIn("'=HYPERLINK",z.read('Peps_Notebook_Player_Links.csv').decode('utf-8-sig'))
            self.assertNotIn('settings',','.join(z.namelist()))
    def test_backup_restores_and_retention(self):
        mid=self.match('1');now=datetime(2026,10,1,tzinfo=timezone.utc)
        for i in range(9): path=daily_backup(self.db,now+timedelta(days=i))
        self.assertEqual(len(list(path.parent.glob('*.sqlite3'))),7)
        restored=Database(path);self.assertEqual(restored.match(mid)['match_type'],'Practice')
        self.assertEqual(restored.one('PRAGMA quick_check')['quick_check'],'ok')
    def test_current_backup_refreshes(self):
        path=daily_backup(self.db);mid=self.match('1');daily_backup(self.db,refresh=True)
        self.assertIsNotNone(Database(path).match(mid))