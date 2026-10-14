"""RT Football Media as its own Discord identity sharing Pep's database."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from gaffergpt.bot import DraftView,GafferBot
from gaffergpt.config import Config
from gaffergpt.rt_media import RTMediaBot


class RTMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.pep=GafferBot(Config('pep-token',42,30,database_path=str(Path(self.tmp.name)/'pep.db'),rt_media_token='rt-token'))
        self.rt=RTMediaBot(self.pep);self.pep.rt_media=self.rt
        self.report=self.pep.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',42)['report_id']
    async def asyncTearDown(self):
        await self.pep.close();self.tmp.cleanup()

    async def test_drafts_use_rt_media_only_once_it_is_connected(self):
        self.assertIs(self.pep.media_desk(),self.pep)
        self.rt.is_ready=lambda:True
        self.assertIs(self.pep.media_desk(),self.rt);self.assertIs(self.rt.media_desk(),self.rt)

    async def test_newsroom_shares_records_but_requests_no_message_content(self):
        self.assertIs(self.rt.db,self.pep.db)
        self.assertFalse(self.rt.intents.message_content);self.assertFalse(self.rt.intents.members)
        view=DraftView(self.rt,self.report)
        self.assertIn('Publish to RT Football Media',[c.label for c in view.children])
        self.assertTrue(self.rt.manager(SimpleNamespace(user=SimpleNamespace(id=42),guild_id=None)))
        self.assertFalse(self.rt.manager(SimpleNamespace(user=SimpleNamespace(id=7,roles=[]),guild_id=30)))

    async def test_only_coach_photo_for_an_open_draft_is_handled(self):
        self.rt.attach_weekly_photo=AsyncMock()
        def dm(author,attachments=('photo',),content=''):
            return SimpleNamespace(author=SimpleNamespace(id=author,bot=False),guild=None,content=content,attachments=list(attachments),reply=AsyncMock())
        await self.rt.on_message(dm(42));await self.rt.on_message(dm(7))
        self.rt.attach_weekly_photo.assert_not_awaited()
        self.pep.db.set_setting('weekly_photo_awaiting',str(self.report))
        await self.rt.on_message(dm(7));self.rt.attach_weekly_photo.assert_not_awaited()
        message=dm(42);await self.rt.on_message(message)
        self.rt.attach_weekly_photo.assert_awaited_once_with(message,self.report)
        await self.rt.on_message(dm(42,(),'cancel photo'))
        self.assertEqual(self.pep.db.setting('weekly_photo_awaiting'),'')


if __name__=='__main__':
    unittest.main()
