import asyncio
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
        from unittest.mock import patch
        self.media_patch=patch('gaffergpt.bot.report_attachments',AsyncMock(return_value=[]))
        self.media_patch.start();self.addCleanup(self.media_patch.stop)
        self.text_patch=patch('gaffergpt.bot.send_checked_article',AsyncMock())
        self.text_patch.start();self.addCleanup(self.text_patch.stop)
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

class PhotoAndAwardTests(DMWorkflowTests):
    async def test_player_suggestion_confirmed_and_photo_attached(self):
        self.bot.recap_reader.extract.return_value={'lines':['2026-10-15 | Official Home | Chelsea | 3-1'],'questions':[],'player_name':'Zak','player_evidence':'Suggestion: 2 assists in the submitted week.'}
        message=self.message();await self.bot.on_message(message)
        self.assertIn('Pep recommends Player of the Week: Zak',message.reply.call_args.args[0]);self.assertIn('1 league matches. A normal MPL week is four',message.reply.call_args.args[0])
        view=message.reply.call_args.kwargs['view']
        interaction=SimpleNamespace(user=SimpleNamespace(id=1),response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        await view.children[2].callback(interaction)
        message.id=100;message.content='';message.attachments=[SimpleNamespace(size=15,read=AsyncMock(return_value=b'\x89PNG\r\n\x1a\nphoto'))]
        await self.bot.on_message(message)
        owner=SimpleNamespace(send=AsyncMock());self.bot.fetch_user=AsyncMock(return_value=owner)
        await view.children[0].callback(interaction)
        self.assertEqual(len(owner.send.call_args.kwargs['files']),1)
        self.assertIn('Zak — Suggestion: 2 assists',self.bot.db.report(self.rid)['article'])

class RecapReliabilityTests(DMWorkflowTests):
    async def test_date_correction_reuses_original_screenshot_after_restart(self):
        message=self.message();message.content='First match away, second match home, October 13, 2026.'
        screenshot=b'\x89PNG\r\n\x1a\nmatch results'
        message.attachments=[SimpleNamespace(size=len(screenshot),read=AsyncMock(return_value=screenshot))]
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':['October 13 or October 14?']}
        await self.bot.on_message(message)
        await self.bot.close()
        self.bot=GafferBot(self.bot.config)
        self.bot.recap_reader=SimpleNamespace(extract=AsyncMock(return_value={'lines':['2026-10-13 | Official Away | Middlesbrough | 1-0'],'questions':[]}))
        message.id=100;message.content="It's October 13, 2026.";message.attachments=[]
        await self.bot.on_message(message)
        supplied,images=self.bot.recap_reader.extract.call_args.args[:2]
        self.assertIn('First match away, second match home',supplied)
        self.assertIn("It's October 13, 2026.",supplied)
        self.assertEqual(images,[(screenshot,'image/png')])
        self.assertIn('2026-10-13',message.reply.call_args.args[0])
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))

    async def test_long_clarification_is_delivered_with_full_details(self):
        question='Please confirm the supplied match classification. '*70
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':[question]}
        message=self.message();await self.bot.on_message(message)
        self.assertLessEqual(len(message.reply.call_args.args[0]),2000)
        attachment=message.reply.call_args.kwargs['file']
        self.assertIn(question,attachment.fp.getvalue().decode())
        attachment.close()

    async def test_new_screenshot_replaces_pending_clarification_context(self):
        message=self.message();message.content='Original recap'
        first=b'\x89PNG\r\n\x1a\nfirst'
        message.attachments=[SimpleNamespace(size=len(first),read=AsyncMock(return_value=first))]
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':['Confirm the date?']}
        await self.bot.on_message(message)
        second=b'\x89PNG\r\n\x1a\nsecond'
        message.id=100;message.content='Replacement recap'
        message.attachments=[SimpleNamespace(size=len(second),read=AsyncMock(return_value=second))]
        await self.bot.on_message(message)
        supplied,images=self.bot.recap_reader.extract.call_args.args[:2]
        self.assertEqual(supplied,'Replacement recap')
        self.assertEqual(images,[(second,'image/png')])

    async def test_expired_screenshot_context_is_not_reused(self):
        message=self.message();message.content='Original recap'
        image=b'\x89PNG\r\n\x1a\nfirst'
        message.attachments=[SimpleNamespace(size=len(image),read=AsyncMock(return_value=image))]
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':['Confirm the date?']}
        await self.bot.on_message(message)
        key=f'recap_context:{self.rid}';saved=json.loads(self.bot.db.setting(key))
        saved['expires_at']='2000-01-01T00:00:00+00:00';self.bot.db.set_setting(key,json.dumps(saved))
        message.id=100;message.content='A new recap';message.attachments=[]
        await self.bot.on_message(message)
        supplied,images=self.bot.recap_reader.extract.call_args.args[:2]
        self.assertEqual(supplied,'A new recap');self.assertEqual(images,[])

    async def test_invalid_attachment_does_not_discard_pending_screenshot(self):
        message=self.message();message.content='Original recap'
        image=b'\x89PNG\r\n\x1a\nfirst'
        message.attachments=[SimpleNamespace(size=len(image),read=AsyncMock(return_value=image))]
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':['Confirm the date?']}
        await self.bot.on_message(message)
        message.id=100;message.content='';message.attachments=[SimpleNamespace(size=5,read=AsyncMock(return_value=b'video'))]
        await self.bot.on_message(message)
        self.assertIn('PNG',message.reply.call_args.args[0])
        message.id=101;message.content='October 13, 2026';message.attachments=[]
        await self.bot.on_message(message)
        supplied,images=self.bot.recap_reader.extract.call_args.args[:2]
        self.assertIn('Original recap',supplied)
        self.assertEqual(images,[(image,'image/png')])

    async def test_emoji_clarification_fits_discord_character_count(self):
        question='😀'*1100
        self.bot.recap_reader.extract.return_value={'lines':[],'questions':[question]}
        message=self.message();await self.bot.on_message(message)
        self.assertLessEqual(len(message.reply.call_args.args[0].encode('utf-16-le'))//2,2000)
        attachment=message.reply.call_args.kwargs['file']
        self.assertIn(question,attachment.fp.getvalue().decode())
        attachment.close()

    async def test_long_preview_and_award_explanations_fit_discord(self):
        self.bot.recap_reader.extract.return_value={
            'lines':[f'2026-10-15 | Official Home | Test opponent {i} | 1-0' for i in range(30)],'questions':[],
            'player_name':'A'*100,'player_evidence':'B'*500,'runner_up':'C'*100,'runner_up_evidence':'D'*500}
        message=self.message();await self.bot.on_message(message)
        self.assertLessEqual(len(message.reply.call_args.args[0]),2000)
        attachment=message.reply.call_args.kwargs['file']
        full=attachment.fp.getvalue().decode()
        self.assertIn('Test opponent 29',full);self.assertIn('D'*500,full)
        attachment.close()

    async def test_busy_confirmation_is_acknowledged_without_waiting(self):
        message=self.message();await self.bot.on_message(message)
        view=message.reply.call_args.kwargs['view']
        interaction=SimpleNamespace(user=SimpleNamespace(id=1),response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        await self.bot.coaching_lock.acquire()
        try:
            await asyncio.wait_for(view.children[0].callback(interaction),timeout=0.5)
        finally:
            self.bot.coaching_lock.release()
        interaction.response.defer.assert_awaited_once()
        self.assertIn('already',interaction.followup.send.call_args.args[0])
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))
        self.assertFalse(json.loads(self.bot.db.setting('recap_preview:99'))['used'])

    async def test_expired_confirmation_does_not_save_or_consume_preview(self):
        import discord
        message=self.message();await self.bot.on_message(message)
        view=message.reply.call_args.kwargs['view']
        error=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),{'code':10062,'message':'Unknown interaction'})
        interaction=SimpleNamespace(user=SimpleNamespace(id=1),response=SimpleNamespace(defer=AsyncMock(side_effect=error),send_message=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        with self.assertRaises(discord.NotFound):await view.children[0].callback(interaction)
        self.assertFalse(self.bot.db.rows('SELECT * FROM matches'))
        self.assertFalse(json.loads(self.bot.db.setting('recap_preview:99'))['used'])

    async def test_message_delivery_failure_logs_code_and_sends_short_reply(self):
        import discord
        message=self.message()
        try:
            raise discord.HTTPException(SimpleNamespace(status=400,reason='Bad Request'),{'code':50035,'message':'Invalid Form Body'})
        except discord.HTTPException:
            with self.assertLogs('gaffergpt',level='ERROR') as captured:
                await self.bot.on_error('on_message',message)
        self.assertIn('50035',' '.join(captured.output))
        message.reply.assert_awaited_once()
        self.assertLessEqual(len(message.reply.call_args.args[0]),2000)

class PracticeClarificationRegressionTests(unittest.TestCase):
    def test_practice_null_venue_and_repeated_confirmation_cannot_block(self):
        result=validate_extraction({'results':[{'date':'2026-10-07','type':'Practice','opponent':'Chelsea','birmingham_score':2,'opponent_score':2}],
            'questions':['Confirm Home/Away is null?','Coach says practice; confirm Type=Practice?']})
        self.assertEqual(result['questions'],[])
        self.assertEqual(result['lines'],['2026-10-07 | Practice | Chelsea | 2-2'])
    def test_missing_score_or_invalid_date_still_requires_clarification(self):
        for date,score in [('2026-10-07',None),('2026-99-99',2)]:
            result=validate_extraction({'results':[{'date':date,'type':'Practice','opponent':'Chelsea','birmingham_score':score,'opponent_score':2}],'questions':[]})
            self.assertTrue(result['questions']);self.assertEqual(result['lines'],[])


class RunnerUpTests(unittest.TestCase):
    def test_runner_up_needs_a_winner_and_a_different_name(self):
        from gaffergpt.recap_intake import validate_extraction
        row={'date':'2026-10-15','type':'Official Home','opponent':'Chelsea','birmingham_score':3,'opponent_score':1}
        base={'results':[row],'questions':[],'recommended_player':'Zak','player_evidence':'2 goals','runner_up':'Tru','runner_up_evidence':'8.4 rating'}
        self.assertEqual(validate_extraction(base)['runner_up'],'Tru')
        self.assertEqual(validate_extraction(dict(base,runner_up='Zak'))['runner_up'],'')
        self.assertEqual(validate_extraction(dict(base,recommended_player=None))['runner_up'],'')
