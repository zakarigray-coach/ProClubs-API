import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.weekly_intake import save_submission, save_photo, content
from gaffergpt.reporter import Reporter

class WeeklyIntakeTests(unittest.TestCase):
    def setUp(self):
        self.root=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.root.name)/'central.sqlite3')
        self.report=self.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00','1')['report_id']
    def tearDown(self): self.root.cleanup()
    def submit(self,results,**kw):
        return save_submission(self.db,self.report,'1','guild',results,**kw)
    def test_doubleheader_practice_duplicate_and_selection(self):
        rows='2026-10-15 | Official Home | Chelsea | 3-1\n2026-10-15 | Official Away | Chelsea | 2-1\n2026-10-14 | Practice | Chelsea | 1-3'
        self.assertEqual(self.submit(rows),3)
        self.assertEqual(self.submit(rows),0)
        self.assertEqual(len(self.db.selected(self.report)),0)
        matches=self.db.rows('SELECT * FROM matches ORDER BY match_id')
        self.assertEqual(sum(m['counts_official'] for m in matches),2)
        self.db.replace_page_selection(self.report,[m['match_id'] for m in matches],[matches[0]['match_id']])
        with self.assertRaises(ValueError): Reporter(self.db).generate(self.report)
        self.db.confirm_report(self.report)
        article=Reporter(self.db).generate(self.report)
        self.assertIn('3–1',article)
        self.assertNotIn('2–1',article)
        self.assertNotIn('1–3',article)
        self.assertEqual(self.db.report(self.report)['status'],'draft')
        reopened=Database(Path(self.root.name)/'central.sqlite3')
        self.assertEqual(len(reopened.rows('SELECT * FROM matches')),3)
    def test_invalid_batch_is_atomic_and_owner_only(self):
        with self.assertRaises(ValueError): self.submit('2026-10-15 | Official Home | Chelsea | 3-1\nbad data')
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),0)
        with self.assertRaises(ValueError): save_submission(self.db,self.report,'2','guild','')
        with self.assertRaises(ValueError): self.submit('2026-10-20 | Practice | Chelsea | 1-1')
        with self.assertRaises(ValueError): self.submit('',player_name='Zak')
    def test_identical_fixtures_still_separate(self):
        line='2026-10-15 | Official Home | Chelsea | 1-1'
        self.assertEqual(self.submit(line+'\n'+line),2)
        self.assertEqual(self.submit(line+'\n'+line),0)
    def test_optional_photo_and_mention_persist(self):
        self.submit('2026-10-15 | Official Home | Chelsea | 3-1',notes='PCT reports forced passing.',player_name='<@123>',player_evidence='Two assists, confirmed by management.')
        save_photo(self.db,self.report,'1',b'\x89PNG\r\n\x1a\nexample')
        with self.assertRaises(ValueError): save_photo(self.db,self.report,'1',b'not an image')
        with self.assertRaises(ValueError): save_photo(self.db,self.report,'1',b'a'*(8*1024*1024+1))
        m=self.db.rows('SELECT match_id FROM matches')[0]['match_id']
        self.db.replace_page_selection(self.report,[m],[m]);self.db.confirm_report(self.report)
        article=Reporter(self.db).generate(self.report)
        self.assertIn('<@123> — Two assists',article)
        self.assertIn('Management-supplied observations',article)
        self.assertEqual(content(self.db,self.report)['photo_extension'],'png')
        self.db.execute("UPDATE weekly_reports SET status='approved' WHERE report_id=?",(self.report,))
        with self.assertRaises(ValueError): self.submit('')
        with self.assertRaises(ValueError): save_photo(self.db,self.report,'1',b'\x89PNG\r\n\x1a\n')
