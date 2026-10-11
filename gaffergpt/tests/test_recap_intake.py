import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from gaffergpt.bot import GafferBot,RecapConfirmView
from gaffergpt.config import Config
from gaffergpt.recap_intake import validate_extraction

class ExtractionTests(unittest.TestCase):
    def test_complete_fact_and_missing_fact(self):
        good={'date':'2026-10-15','type':'Official Home','opponent':'Chelsea','birmingham_score':3,'opponent_score':1}
        read=validate_extraction({'results':[good],'questions':[]})
        self.assertEqual(read['lines'],['2026-10-15 | Official Home | Chelsea | 3-1'])
        for key in good:
            read=validate_extraction({'results':[{**good,key:None}],'questions':[]})
            self.assertTrue(read['questions']);self.assertFalse(read['lines'])
    def test_bad_shape_rejected(self):
        for value in [None,{'results':'invent'},{'results':[1]}]:
            with self.assertRaises(ValueError): validate_extraction(value)

class DMWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root=tempfile.TemporaryDirectory()
        self.bot=GafferBot(Config('test',1,2,database_path=str(Path(self.root.name)/'pep.db')))
        self.rid=self.bot.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',1)['report_id']
        self.bot.db.set_setting('weekly_dm_awaiting',str(self.rid))
        self.bot.recap_reader=SimpleNamespace(extract=AsyncMock(return_value={'lines':['2026-10-15 | Official Home | Chelsea | 3-1'],'questions':[]}))
    async def asyncTearDown(self):
        await self.bot.close();self.root.cleanup()
    def message(self):
        class Typing:
            async def __aenter__(self): pass
            async def __aexit__(self,*args): pass
        return SimpleNamespace(id=99,guild=None,author=SimpleNamespace(id=1,bot=False),content='Birmingham weekly league results',attachments=[],reply=AsyncMock(),channel=SimpleNamespace(typing=lambda:Typing()))
    async def test_dm_preview_then_confirm_private_draft(self):
        message=self.message();await self.bot.on_message(message)
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))
        view=message.reply.call_args.kwargs['view'];self.assertTrue(view.is_persistent())
        # Reconstruct from persisted preview, as startup does.
        view=RecapConfirmView(self.bot,self.rid,'99')
        owner=SimpleNamespace(send=AsyncMock());self.bot.fetch_user=AsyncMock(return_value=owner)
        interaction=SimpleNamespace(user=SimpleNamespace(id=1),response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        await view.children[0].callback(interaction)
        self.assertEqual(self.bot.db.report(self.rid)['status'],'draft')
        self.assertEqual(len(self.bot.db.selected(self.rid)),1)
        owner.send.assert_awaited_once()
        self.assertIn('Nothing published',owner.send.call_args.kwargs['content'])
        await view.children[0].callback(interaction);owner.send.assert_awaited_once()
    async def test_partial_data_asks_and_does_not_import(self):
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':['Was this home or away?']}
        message=self.message();await self.bot.on_message(message)
        self.assertIn('home or away',message.reply.call_args.args[0])
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))
    async def test_photo_is_passed_to_reader_as_image_not_feature_photo(self):
        message=self.message();message.content=''
        message.attachments=[SimpleNamespace(size=12,read=AsyncMock(return_value=b'\x89PNG\r\n\x1a\nphoto'))]
        await self.bot.on_message(message)
        self.assertEqual(self.bot.recap_reader.extract.call_args.args[1][0][1],'image/png')
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))
