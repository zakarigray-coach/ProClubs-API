"""Recap-only scope and the approved visual output, with no paid provider calls."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from PIL import Image
from gaffergpt.database import Database,utcnow
from gaffergpt.reporter import Reporter
from gaffergpt.report_verification import build_fact_sheet,validate_final,digest
from gaffergpt.article_writer import WRITING_VERSION
from gaffergpt.article_layout import media_pages,weekly_cover,article_pages
from gaffergpt.weekly_intake import save_submission,save_photo
from gaffergpt.competitions import configure_report,set_match_details
from gaffergpt.bot import GafferBot,ReportView,eligible_recap_matches,assert_recap_scope
from gaffergpt.config import Config

class SourceWriter:
    """Deterministic fixture reporter; validates every score before recording a passed source check."""
    model='test-only';calls=0
    def write(self,packet):
        self.calls+=1;self.last_fact_sheet=build_fact_sheet(packet);sentences=[];claims=[]
        for key,fact in self.last_fact_sheet['facts'].items():
            if fact['kind']!='fixture':continue
            value=fact['value'];kind={'Cup':'cup','Practice':'practice'}.get(fact['classification'],'MPL')
            text=f"Birmingham City recorded a {value['for']}–{value['against']} {kind} result against {fact['subject']}."
            sentences.append(text);claims.append({'fact_id':key,'quote':text})
        article={'title':'Birmingham’s contrasting results','body':'\n\n'.join(sentences)}
        self.last_verification=validate_final(article,self.last_fact_sheet,{'claims':claims,'unsupported':[]})
        self.last_verification.update(writing_version=WRITING_VERSION,model=self.model,management_hash=digest(packet.get('management')))
        self.last_attempts=[{'state':'passed','checks':['deterministic_source_test']}]
        return article['title'],article['body']

class MVPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'pep.db');self.bot=GafferBot(Config('test',42,30,database_path=str(self.db.path)));self.writer=SourceWriter()
    async def asyncTearDown(self):await self.bot.close();self.tmp.cleanup()
    def league(self):
        rid=self.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',42)['report_id']
        save_submission(self.db,rid,42,30,'2026-10-15 | Official Home | Chelsea | 3-1\n2026-10-15 | Official Away | Chelsea | 2-2\n2026-10-14 | Practice | Test Club | 9-8')
        rows=self.db.period_matches('2026-10-12','2026-10-19',True);ids=[m['match_id'] for m in rows if m['match_type']=='Official'];self.db.replace_page_selection(rid,[m['match_id'] for m in rows],ids);self.db.confirm_report(rid);return rid
    async def test_mpl_source_selection_media_and_photo_without_ai_recharge(self):
        rid=self.league();assert_recap_scope(self.db,rid);article=Reporter(self.db,writer=self.writer).generate(rid)
        self.assertNotIn('9–8',article);self.assertEqual(len(eligible_recap_matches(self.db,rid)),2)
        self.assertEqual(len(self.db.selected(rid)),2);self.assertEqual(self.db.official_record()['played'],2)
        first=media_pages(self.db,rid);self.assertGreaterEqual(len(first),2);self.assertEqual(Image.open(io.BytesIO(first[0])).size,(1080,760))
        photo=io.BytesIO();Image.new('RGB',(300,400),'red').save(photo,format='PNG');save_photo(self.db,rid,42,photo.getvalue())
        self.assertEqual(self.db.report(rid)['article'],article);second=media_pages(self.db,rid);self.assertNotEqual(second[0],first[0]);self.assertEqual(self.writer.calls,1)
        self.db.confirm_report(rid);self.assertEqual(Reporter(self.db,writer=self.writer).generate(rid),article);self.assertEqual(self.writer.calls,1)
        self.assertEqual(self.db.report(rid)['status'],'draft')
    async def test_removed_session_and_type_controls_leave_recaps_working(self):
        self.assertIsNone(self.bot.tree.get_command('session'));self.assertIsNotNone(self.bot.tree.get_command('cupreport'))
        rid=self.league();view=ReportView(self.bot,rid)
        self.assertFalse(any(getattr(c,'placeholder','')=='Competition / Report Type' for c in view.children))
        self.assertFalse(any('Training Ground' in (getattr(c,'label','') or '') for c in view.children))
        self.assertNotIn('Test Club',self.bot.report_summary(rid))
        practice=next(m['match_id'] for m in self.db.rows('SELECT * FROM matches') if m['match_type']=='Practice');self.db.replace_page_selection(rid,[practice],[practice])
        with self.assertRaises(ValueError):assert_recap_scope(self.db,rid)
    async def test_cup_manual_trigger_idempotency_and_full_media(self):
        key='mpl-pre-season-cup-2026';rid=self.db.open_report('2026-10-13T04:00:00+00:00','2026-10-16T04:00:00+00:00',42,key)['report_id'];configure_report(self.db,rid,key)
        save_submission(self.db,rid,42,30,'2026-10-13 | Cup | Test United | 2-1\n2026-10-15 | Cup | Test City | 1-1');matches=self.db.rows('SELECT * FROM matches')
        for m,stage in zip(matches,('Quarter-final','Semi-final')):set_match_details(self.db,m['match_id'],key,42,'Test manager confirmation',stage=stage)
        ids=[m['match_id'] for m in matches];self.db.replace_page_selection(rid,ids,ids);self.db.confirm_report(rid)
        Reporter(self.db,writer=self.writer).generate(rid);pages=media_pages(self.db,rid)
        self.assertEqual(Image.open(io.BytesIO(pages[0])).size,(1080,1560));self.assertGreaterEqual(len(pages),2);self.assertEqual(self.db.official_record()['played'],0)
        self.assertEqual(self.db.open_report('2026-10-13T04:00:00+00:00','2026-10-16T04:00:00+00:00',42,key)['report_id'],rid)
        interaction=SimpleNamespace(user=SimpleNamespace(id=42),response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        command=self.bot.tree.get_command('cupreport');await command.callback(interaction)
        self.assertEqual(len(self.db.rows('SELECT * FROM weekly_reports')),1)
        self.assertTrue(any(getattr(c,'label','')=='Cup Competition Details' for c in interaction.followup.send.call_args.kwargs['view'].children))
    async def test_generation_failure_and_duplicate_lease_preserve_selection(self):
        rid=self.league();ids=[m['match_id'] for m in self.db.selected(rid)]
        class Broken:
            def write(self,packet):raise RuntimeError('API unavailable')
        with self.assertRaises(RuntimeError):Reporter(self.db,writer=Broken()).generate(rid)
        self.assertEqual([m['match_id'] for m in self.db.selected(rid)],ids);self.assertEqual(self.db.report(rid)['status'],'confirmed')
        self.assertEqual(self.db.rows('SELECT * FROM report_generation_leases'),[])
        self.db.execute("INSERT INTO report_generation_leases VALUES(?,?,'2999-01-01T00:00:00+00:00')",(rid,'other-worker'))
        with self.assertRaisesRegex(ValueError,'already being prepared'):Reporter(self.db,writer=self.writer).generate(rid)
        self.assertEqual(self.writer.calls,0)
    async def test_long_headline_photo_area_and_article_pagination(self):
        title='Birmingham City find the decisive contribution in a week of contrasting results across their selected MPL fixtures'
        png=weekly_cover(title,'October 12–18, 2026',dict(wins=1,draws=1,losses=0,goals_for=5,goals_against=3),'DaddyGray10420')
        self.assertEqual(Image.open(io.BytesIO(png)).size,(1080,760))
        body='\n\n'.join(['Birmingham City’s selected fixtures gave the sports desk contrasting results and individual contributions to report. '*12]*6)
        pages=article_pages(title,body,'Raine','October 12–18, 2026');self.assertGreater(len(pages),1)
        for page in pages:self.assertEqual(Image.open(io.BytesIO(page)).size,(1080,1560))

    async def test_private_historical_sample_preserves_practice_classification(self):
        rid=self.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',42)['report_id']
        save_submission(self.db,rid,42,30,'2026-10-15 | Practice | Chelsea | 3-1')
        ids=[m['match_id'] for m in self.db.rows('SELECT * FROM matches')]
        self.db.replace_page_selection(rid,ids,ids);self.db.confirm_report(rid)
        Reporter(self.db,writer=self.writer).generate(rid)
        with self.assertRaises(ValueError):media_pages(self.db,rid)
        pages=media_pages(self.db,rid,sample=True)
        self.assertGreaterEqual(len(pages),2)
        self.assertEqual(self.db.official_record()['played'],0)
        self.assertEqual(self.db.selected(rid)[0]['match_type'],'Practice')
