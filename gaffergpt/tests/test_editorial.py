import sqlite3
import tempfile
import unittest
from pathlib import Path
from gaffergpt.editorial import choose_editorial, editorial_lead, STYLES


class EditorialTests(unittest.TestCase):
    def test_rotation_and_recent_openings_survive_restarts(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'central.sqlite3'
            recent={'Raine':[],'Teagan':[]}
            for report_id in range(1,25):
                with sqlite3.connect(path) as conn:
                    conn.row_factory=sqlite3.Row
                    conn.execute('CREATE TABLE IF NOT EXISTS weekly_reports (report_id INTEGER PRIMARY KEY)')
                    conn.execute('INSERT INTO weekly_reports VALUES (?)',(report_id,))
                    chosen=choose_editorial(conn,report_id)
                    expected='Raine' if report_id%2 else 'Teagan'
                    self.assertEqual(chosen['reporter'],expected)
                    self.assertNotIn(chosen['opening'],recent[expected][-8:])
                    self.assertEqual(chosen['style'],STYLES[expected])
                    self.assertEqual(choose_editorial(conn,report_id),chosen)
                    recent[expected].append(chosen['opening'])
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM report_editorial').fetchone()[0],24)

    def test_lead_uses_only_given_totals_and_distinguishes_voices(self):
        summary={'scored_matches':2,'wins':1,'draws':1,'losses':0,'goals_for':4,'goals_against':2}
        for reporter in STYLES:
            lead=editorial_lead({'reporter':reporter,'opening':'Opening.'},summary)
            self.assertIn('1 win, 1 draw and 0 defeats',lead)
            self.assertNotIn('Chelsea',lead)
            self.assertNotIn('possession',lead)
        self.assertNotEqual(editorial_lead({'reporter':'Raine','opening':'Opening.'},summary),editorial_lead({'reporter':'Teagan','opening':'Opening.'},summary))
