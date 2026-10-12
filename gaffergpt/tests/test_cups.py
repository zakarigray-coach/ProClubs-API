import asyncio
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from gaffergpt.database import Database,SCHEMA
from gaffergpt.competitions import configure_report,report_event,set_match_details,snapshot,verify_event
from gaffergpt.report_verification import build_fact_sheet,validate_final,ReportHold
from gaffergpt.weekly_intake import save_submission
from gaffergpt.cup_cover import render,render_pages

KEY='mpl-pre-season-cup-2026'

class CupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'test.db';self.db=Database(self.path)
        self.report=self.db.open_report('2026-10-12T04:00:00+00:00','2026-10-19T04:00:00+00:00',42,KEY)
        configure_report(self.db,self.report['report_id'],KEY)
    def add(self,score='2-1',opponent='Test United',stage=None,**details):
        mids=self.db.ingest(str(len(self.db.rows('SELECT * FROM matches'))+1),20,30,'2026-10-13T22:00:00+00:00','Test only',
            [dict(opponent=opponent,birmingham_score=int(score.split('-')[0]),opponent_score=int(score.split('-')[1]))])
        mid=mids[0];set_match_details(self.db,mid,KEY,42,'Test management confirmation',stage=stage,**details)
        return mid
    def packet(self,mids):
        self.db.replace_page_selection(self.report['report_id'],mids,mids)
        return dict(matches=self.db.selected(self.report['report_id']),statistics=[],competition_context=snapshot(self.db,self.report['report_id']))
    def test_seed_has_no_invented_details(self):
        e=report_event(self.db,self.report['report_id'])
        self.assertEqual(e['event_start'],'2026-10-13')
        self.assertEqual(e['name'],'The Minglewood Cup')
        self.assertEqual(e['event_end'],'2026-10-15')
        self.assertIn('Single elimination',e['format'])
        self.assertIn('unconfirmed',e['start_time'])
        self.assertIsNone(e['prizes'])
        self.assertEqual(e['outcome'],'Unknown')
    def test_announced_format_and_season_context_are_source_facts(self):
        sheet=build_fact_sheet(self.packet([self.add()]))
        quote='The single-elimination cup is preseason ahead of Season 4.'
        claims=[{'fact_id':k,'quote':quote} for k,f in sheet['facts'].items() if f['metric'] in ('event_format','season_number')]
        validate_final({'title':'The Minglewood Cup','body':quote},sheet,{'claims':claims,'unsupported':[]})

    def test_cup_excluded_from_league_and_practice(self):
        mid=self.add();sheet=build_fact_sheet(self.packet([mid]))
        self.assertEqual(self.db.official_record()['played'],0)
        self.assertEqual(set(sheet['groups']),{'Cup'})
        self.assertEqual(sheet['groups']['Cup']['summary']['goals_for'],2)
    def test_same_opponent_two_legs_separate_and_aggregate(self):
        a=self.add('2-1',tie_key='semi-a',leg=1,stage='Semi-final')
        b=self.add('1-1',tie_key='semi-a',leg=2,stage='Semi-final')
        sheet=build_fact_sheet(self.packet([a,b]));self.assertEqual(len(sheet['fixtures']),2)
        aggregate=next(f for f in sheet['facts'].values() if f['metric']=='aggregate:semi-a')
        self.assertEqual(aggregate['value']['for'],3);self.assertEqual(aggregate['value']['against'],2)
        self.assertFalse(any(f['metric']=='confirmed_outcome' for f in sheet['facts'].values()))
    def test_group_knockout_and_shootout_do_not_add_goals(self):
        a=self.add('2-1',stage='Group stage',group_bracket='Group A')
        b=self.add('1-1',stage='Quarter-final',extra_time_for=1,extra_time_against=1,penalties_for=5,penalties_against=4)
        sheet=build_fact_sheet(self.packet([a,b]))
        self.assertEqual(sheet['groups']['Cup']['summary']['goals_for'],3)
        self.assertEqual(sheet['groups']['Cup']['summary']['draws'],1)
        facts=[f['metric'] for f in sheet['facts'].values()]
        self.assertIn(f'match:{b}:penalties_for',facts)
        self.assertIn(f'match:{a}:group_bracket',facts)
    def test_unknown_progression_and_unconfirmed_award_blocked(self):
        sheet=build_fact_sheet(self.packet([self.add()]))
        for body in ('Birmingham advanced from the cup.', 'Birmingham were champions.', 'Test Player was Player of the Tournament.'):
            with self.assertRaises(ValueError):validate_final({'title':'Birmingham cup report','body':body},sheet,{'claims':[],'unsupported':[]})

    def test_invalid_shootout_or_extra_time_rejected(self):
        with self.assertRaises(ValueError):self.add('2-1',penalties_for=5,penalties_against=4)
        with self.assertRaises(ValueError):self.add('1-1',extra_time_for=2,extra_time_against=1)
    def test_unknown_leg_does_not_invent_aggregate(self):
        a=self.add('2-1',tie_key='tie-a',leg=1)
        sheet=build_fact_sheet(self.packet([a]))
        self.assertFalse(any(f['metric'].startswith('aggregate:') for f in sheet['facts'].values()))
    def test_different_report_types_same_week_coexist(self):
        league=self.db.open_report(self.report['week_start'],self.report['week_end'],42)
        self.assertNotEqual(league['report_id'],self.report['report_id'])
        self.assertEqual(self.db.open_report(self.report['week_start'],self.report['week_end'],42,KEY)['report_id'],self.report['report_id'])
    def test_mixed_selection_held(self):
        a=self.add();b=self.add()
        self.db.classify(b,'Practice','Unknown',42)
        with self.assertRaises(ReportHold):build_fact_sheet(self.packet([a,b]))
    def test_progression_requires_format_and_confirmation(self):
        self.db.execute('UPDATE competitions SET format=NULL WHERE competition_key=?',(KEY,))
        with self.assertRaises(ValueError):configure_report(self.db,self.report['report_id'],KEY,'Champions','Coach confirms')
        self.db.execute('UPDATE competitions SET format=? WHERE competition_key=?',('Knockout final',KEY))
        with self.assertRaises(ValueError):configure_report(self.db,self.report['report_id'],KEY,'Champions')
        configure_report(self.db,self.report['report_id'],KEY,'Champions','Coach confirms final won 2-1')
    def test_losing_two_leg_final_cannot_claim_champions(self):
        a=self.add('2-0',tie_key='final-a',leg=1,stage='Final')
        b=self.add('0-3',tie_key='final-a',leg=2,stage='Final')
        configure_report(self.db,self.report['report_id'],KEY,'Champions','Coach supplied outcome')
        with self.assertRaises(ReportHold):build_fact_sheet(self.packet([a,b]))

    def test_award_scope_required(self):
        with self.assertRaises(ValueError):configure_report(self.db,self.report['report_id'],KEY,award_label='Player of the Tournament')
    def test_cup_intake_requires_explicit_setup(self):
        league=self.db.open_report(self.report['week_start'],self.report['week_end'],42)
        with self.assertRaises(ValueError):save_submission(self.db,league['report_id'],42,30,'2026-10-13 | Cup | Test United | 2-1')
        self.assertEqual(self.db.rows('SELECT * FROM matches'),[])
        save_submission(self.db,self.report['report_id'],42,30,'2026-10-13 | Cup | Test United | 2-1')
        self.assertEqual(self.db.rows('SELECT * FROM matches')[0]['match_type'],'Cup')
    def test_cover_fixed_size_and_long_text_extra_card(self):
        event=report_event(self.db,self.report['report_id'])
        png=render(event,'Birmingham find their cup finish','Test Player',sample=True)
        self.assertEqual(Image.open(io.BytesIO(png)).size,(1080,1560))
        event['name']='Minglewood Pre-Season Invitational Football Cup and International Clubs Tournament Championship'
        pages=render_pages(event,'Birmingham discover the difference between a promising start and a decisive finish as the tournament brings contrasting results across selected fixtures',sample=True)
        self.assertGreater(len(pages),1)
        for page in pages:self.assertEqual(Image.open(io.BytesIO(page)).size,(1080,1560))
    def test_legacy_migration_keeps_child_records_and_restart(self):
        path=Path(self.temp.name)/'legacy.db'
        legacy=SCHEMA.replace("'Official','Cup','Practice'","'Official','Practice'")
        legacy=legacy.replace(" OR (match_type='Cup' AND classification_status='Classified' AND counts_official=0)\n",'')
        legacy=legacy.replace(" report_key TEXT NOT NULL DEFAULT 'mpl-league',\n",'').replace('UNIQUE(owner_id,week_start,week_end,report_key)','UNIQUE(owner_id,week_start,week_end)')
        with sqlite3.connect(path) as conn:
            conn.executescript(legacy)
            conn.execute("INSERT INTO matches(match_id,source_message_id,source_channel_id,source_guild_id,detected_at,played_at,raw_recap) VALUES(7,'a','b','c','now','now','Original')")
            conn.execute("INSERT INTO weekly_reports(report_id,week_start,week_end,owner_id,created_at) VALUES(9,'2026-10-12','2026-10-19','42','now')")
            conn.execute('INSERT INTO report_matches VALUES(9,7)')
            conn.execute("INSERT INTO weekly_jobs(job_key,report_id,due_at) VALUES('Friday',9,'2026-10-16')")
            conn.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES(7,'player','Test Player','goals',2)")
        restored=Database(path);restored=Database(path)
        self.assertEqual(restored.match(7)['raw_recap'],'Original')
        self.assertEqual(restored.selected(9)[0]['match_id'],7)
        self.assertEqual(restored.rows('SELECT * FROM weekly_jobs')[0]['job_key'],'Friday')
        self.assertEqual(restored.rows('SELECT * FROM match_statistics')[0]['value'],2)
        self.assertEqual(restored.rows('PRAGMA foreign_key_check'),[])
        self.assertTrue(Path(str(path)+'.pre-cup.bak').exists())

class CupViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_modal_fields_obey_discord_limits(self):
        from gaffergpt.bot import CupEventModal,CupMatchModal,CupAwardModal
        for cls in (CupEventModal,CupMatchModal,CupAwardModal):
            self.assertLessEqual(len(cls.__modal_children_items__),5)
            for field in cls.__modal_children_items__.values():
                self.assertLessEqual(len(field.label),45)
                self.assertLessEqual(len(field.placeholder or ''),100)


    async def test_cup_and_legacy_menus_fit_discord(self):
        from gaffergpt.bot import GafferBot,ReportView
        from gaffergpt.config import Config
        with tempfile.TemporaryDirectory() as tmp:
            bot=GafferBot(Config('test',42,30,database_path=str(Path(tmp)/'db')))
            try:
                report=bot.db.open_report('2026-10-12','2026-10-19',42,KEY)
                configure_report(bot.db,report['report_id'],KEY)
                view=ReportView(bot,report['report_id'])
                self.assertFalse(any(getattr(c,'placeholder',None)=='Competition / Report Type' for c in view.children))
                self.assertTrue(any(getattr(c,'label',None)=='Cup Competition Details' for c in view.children))
            finally:await bot.close()
