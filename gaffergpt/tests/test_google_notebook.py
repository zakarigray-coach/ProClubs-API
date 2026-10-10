import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from gaffergpt.database import Database
from gaffergpt.google_notebook import GoogleNotebook, cell, snapshot, update_requests
from gaffergpt.notebook import TABLES
from gaffergpt.parser import parse_recap


def metadata():
    return {'sheets': [{'properties': {'title': title, 'sheetId': i,
        'gridProperties': {'rowCount': 1000, 'columnCount': 26}}}
        for i, title in enumerate(['Start Here', *TABLES])]}


class Response:
    def __init__(self, status, data=None):
        self.status_code = status
        self.data = data
    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.calls = []
        self.status = 200
    def get(self, url, **kwargs):
        self.calls.append(('get', url, kwargs))
        return Response(200, metadata())
    def post(self, url, **kwargs):
        self.calls.append(('post', url, kwargs))
        return Response(self.status)


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'pep.db')
        self.session = Session()
        self.mirror = GoogleNotebook(self.db, 'a' * 30, self.session)
    def tearDown(self):
        self.temp.cleanup()
    def match(self, message='1'):
        text = 'MPL Birmingham 1-3 Chelsea'
        return self.db.ingest(message, 20, 30, '2026-10-10T21:00:00+00:00',
                              text, parse_recap(text))[0]
    def test_formula_text_and_discord_ids_are_literal(self):
        self.assertEqual(cell('=IMPORTXML("x")')['userEnteredValue'],
                         {'stringValue': '=IMPORTXML("x")'})
        self.assertEqual(cell('811045460508147752')['userEnteredValue'],
                         {'stringValue': '811045460508147752'})
        self.assertEqual(cell(0)['userEnteredValue'], {'numberValue': 0})
        self.assertEqual(cell(None), {})
    def test_exports_every_match_without_changing_classification(self):
        mid = self.match()
        data = snapshot(self.db)
        row = dict(zip(data['Matches'][0], data['Matches'][1]))
        self.assertEqual(row['match_type'], 'Unknown')
        self.assertEqual(row['counts_official'], 0)
        self.assertEqual(self.db.one('SELECT match_type FROM matches WHERE match_id=?', (mid,))['match_type'], 'Unknown')
        self.assertNotIn('settings', data)
        self.assertNotIn('classification_history', data)
    def test_no_individual_development_stats_exported(self):
        mid = self.match()
        self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES (?,'player','DaddyGray10420','rating',6.4)", (mid,))
        self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES (?,'team','birmingham','shots',7)", (mid,))
        rows = snapshot(self.db)['Club_Stats']
        self.assertEqual(len(rows), 2)
        self.assertEqual(dict(zip(rows[0], rows[1]))['subject_type'], 'team')
    def test_success_skip_unchanged_and_classification_refresh(self):
        mid = self.match()
        self.assertTrue(self.mirror.sync())
        self.assertFalse(self.mirror.sync())
        self.assertEqual(len(self.session.calls), 2)
        self.db.classify(mid, 'Practice', 'Unknown', 42)
        self.assertTrue(self.mirror.sync())
        self.assertIsNotNone(self.db.setting('notebook_last_synced_at'))
    def test_failure_retries_and_never_marks_success(self):
        self.session.status = 403
        with self.assertRaises(RuntimeError):
            self.mirror.sync()
        self.assertIsNone(self.mirror.fingerprint)
        self.assertIsNone(self.db.setting('notebook_last_synced_at'))
        self.session.status = 200
        self.assertTrue(self.mirror.sync())
    def test_restart_refreshes_even_if_no_new_records(self):
        self.assertTrue(self.mirror.sync())
        restarted = GoogleNotebook(self.db, 'a' * 30, self.session)
        self.assertTrue(restarted.sync())
    def test_atomic_batch_clears_old_rows_and_preserves_formatting(self):
        self.match()
        requests = update_requests(snapshot(self.db), metadata(), '2026-10-10')
        update = requests[0]['updateCells']
        self.assertEqual(update['range']['endRowIndex'], 1000)
        self.assertEqual(update['fields'], 'userEnteredValue')
        self.assertEqual(len(update['rows']), 2)
        self.assertEqual(requests[-1]['updateCells']['start']['columnIndex'], 1)
    def test_missing_tab_fails_before_writing(self):
        bad = metadata()
        bad['sheets'].pop()
        with self.assertRaises(ValueError):
            update_requests(snapshot(self.db), bad, 'now')
    def test_incomplete_configuration_fails_safely(self):
        with patch.dict('os.environ', {'PEP_GOOGLE_SERVICE_ACCOUNT_JSON': '',
                                      'PEP_NOTEBOOK_SPREADSHEET_ID': ''}):
            self.assertIsNone(GoogleNotebook.from_environment(self.db))
        with patch.dict('os.environ', {'PEP_GOOGLE_SERVICE_ACCOUNT_JSON': '{}',
                                      'PEP_NOTEBOOK_SPREADSHEET_ID': 'a' * 30}):
            with self.assertRaises(ValueError):
                GoogleNotebook.from_environment(self.db)
