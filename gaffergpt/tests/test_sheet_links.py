import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.sheet_links import parse_row, process_rows
from gaffergpt.google_notebook import GoogleNotebook

USER = '811045460508147752'
OTHER = '911045460508147752'


class SheetLinksTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'pep.db')
        self.verified = []
    def tearDown(self):
        self.tmp.cleanup()
    async def member(self, uid):
        self.verified.append(uid)
        return 'VerifiedUsername'
    async def test_link_and_restart_are_idempotent(self):
        row = ['DaddyGray10420', USER]
        results = await process_rows(self.db, [row], USER, self.member)
        self.assertEqual(results[0][0], 'Linked')
        linked = self.db.player_link(USER)
        self.assertEqual(linked['username'], 'VerifiedUsername')
        self.assertEqual(linked['linked_by'], USER)
        restarted = Database(self.db.path)
        self.assertEqual(await process_rows(restarted, [row], USER, self.member), results)
        self.assertEqual(len(self.verified), 1)
    async def test_nonmember_never_saved(self):
        async def not_member(uid): raise LookupError()
        result = await process_rows(self.db, [['Player', USER]], USER, not_member)
        self.assertIn('not found', result[0][0])
        self.assertIsNone(self.db.player_link(USER))
    async def test_duplicates_block_all_affected_rows(self):
        results = await process_rows(self.db, [['Player', USER], ['Other', USER]], USER, self.member)
        self.assertTrue(all('Duplicate' in r[0] for r in results))
        results = await process_rows(self.db, [['Player', USER], ['player', OTHER]], USER, self.member)
        self.assertTrue(all('Duplicate' in r[0] for r in results))
        self.assertEqual(self.verified, [])
    async def test_existing_links_cannot_be_overwritten(self):
        self.db.link_player(USER, 'coach', 'Original', USER)
        results = await process_rows(self.db, [['Changed', USER], ['Original', OTHER]], USER, self.member)
        self.assertTrue(all('conflicts' in r[0] for r in results))
        self.assertEqual(self.db.player_link(USER)['player_name'], 'Original')
    async def test_concurrent_discord_correction_wins(self):
        async def concurrent(uid):
            self.db.link_player(uid, 'coach', 'DiscordCorrection', USER)
            return 'Username'
        results = await process_rows(self.db, [['SheetRequest', USER]], USER, concurrent)
        self.assertIn('conflicts', results[0][0])
        self.assertEqual(self.db.player_link(USER)['player_name'], 'DiscordCorrection')
    async def test_verify_failure_retries(self):
        async def failed(uid): raise RuntimeError('Discord unavailable')
        row = [['Player', USER]]
        result = await process_rows(self.db, row, USER, failed)
        self.assertIn('retry', result[0][0])
        self.assertIsNone(self.db.player_link(USER))
        self.assertEqual((await process_rows(self.db, row, USER, self.member))[0][0], 'Linked')
    def test_numeric_scientific_formula_and_blank_ids(self):
        for value in [int(USER), '8.110454605081478e17', '=123', '<@123>', str(2**64)]:
            self.assertTrue(parse_row(['Player', value])[2])
        self.assertEqual(parse_row(['Player', ''])[2], 'Enter Discord ID')
        self.assertEqual(parse_row(['', '']), ('', '', ''))
    def test_status_write_never_changes_input_or_stale_row(self):
        class Response: status_code = 200
        class Session:
            def __init__(self): self.payloads = []
            def post(self, url, **kwargs):
                self.payloads.append(kwargs['json'])
                return Response()
        session = Session()
        mirror = GoogleNotebook(self.db, 'a'*30, session)
        mirror.link_statuses([['Player', USER]], [['Edited', OTHER]], [['Linked', 'now']])
        self.assertEqual(session.payloads, [])
        mirror.link_statuses([['Player', USER]], [['Player', USER]], [['Linked', 'now']])
        update = session.payloads[0]['data'][0]
        self.assertEqual(update['range'], "'Link Players'!C5:D5")
        self.assertEqual(session.payloads[0]['valueInputOption'], 'RAW')
