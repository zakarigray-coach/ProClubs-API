import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from gaffergpt.database import Database
from gaffergpt.parser import parse_recap,parse_registration
from gaffergpt.reporter import Reporter
from gaffergpt.scheduler import WeeklyScheduler,week_window,friday_due
from gaffergpt.config import Config
from gaffergpt.bot import GafferBot,ReportView,ReviewView,DraftView

UTC=timezone.utc
NOW=datetime(2026,10,9,12,tzinfo=UTC)


class Delivery:
    def __init__(self):
        self.messages={}; self.calls=[]; self.fail=False
    async def find(self,key):
        return self.messages.get(key)
    async def send(self,report_id,key):
        if self.fail:
            raise RuntimeError('offline')
        self.calls.append((report_id,key))
        self.messages[key]=len(self.messages)+1
        return self.messages[key]


class FoundationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'gaffergpt.db')
        self.db=Database(self.path)
        self.delivery=Delivery()
        self.scheduler=WeeklyScheduler(self.db,42,self.delivery)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, message='1', text='Birmingham City 2–1 Chelsea', at='2026-10-06T22:00:00+00:00'):
        return self.db.ingest(message,20,30,at,text,parse_recap(text))

    def report(self,ids):
        r=self.db.open_report(*week_window(NOW),42)
        self.db.replace_page_selection(r['report_id'],ids,ids)
        return r['report_id']

    def test_practice_excluded_official(self):
        mid=self.add()[0]; self.db.classify(mid,'Practice','Unknown',42)
        self.assertEqual(self.db.official_record()['played'],0)
        self.assertEqual(self.db.match(mid)['report_eligible'],1)

    def test_two_official_same_opponent_same_night(self):
        ids=self.add(text='Birmingham City 3–1 Chelsea\nChelsea 1–2 Birmingham City')
        self.assertEqual(len(ids),2)
        for mid,venue in zip(ids,['Home','Away']): self.db.classify(mid,'Official',venue,42)
        self.assertEqual(self.db.official_record()['wins'],2)
        self.assertEqual(self.db.match(ids[1])['birmingham_score'],2)

    def test_practice_and_official_are_distinct(self):
        a=self.add('1')[0]; b=self.add('2')[0]
        self.db.classify(a,'Practice','Unknown',42); self.db.classify(b,'Official','Home',42)
        self.assertEqual(self.db.official_record()['played'],1)

    def test_unknown_never_counted(self):
        mid=self.add()[0]
        self.assertEqual(self.db.match(mid)['match_type'],'Unknown')
        self.assertEqual(self.db.official_record()['played'],0)
        self.assertFalse(self.db.period_matches(*week_window(NOW),True))

    def test_ignored_not_eligible(self):
        mid=self.add()[0]; self.db.classify(mid,'Ignored','Unknown',42)
        self.assertFalse(self.db.period_matches(*week_window(NOW),True))

    def test_duplicate_message(self):
        self.add(); self.assertEqual(self.add(),[])
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),1)

    def test_selected_matches_only(self):
        a=self.add('1')[0]; b=self.add('2',text='Birmingham City 9–0 Arsenal')[0]
        self.db.classify(a,'Official','Home',42); self.db.classify(b,'Official','Away',42)
        rid=self.report([a]); self.db.confirm_report(rid)
        article=Reporter(self.db).generate(rid)
        self.assertIn('Chelsea',article); self.assertNotIn('Arsenal',article)

    def test_restart_preserves_old_schema_and_players(self):
        self.db.register_player(42,'Coach','ST','Advanced Forward')
        mid=self.add()[0]
        again=Database(self.path)
        self.assertIsNotNone(again.match(mid))
        self.assertEqual(again.rows('SELECT * FROM players')[0]['username'],'Coach')
        self.assertEqual(again.one('PRAGMA integrity_check')['integrity_check'],'ok')

    def test_original_phase_one_database_upgrade(self):
        path=str(Path(self.tmp.name)/'old.db')
        conn=sqlite3.connect(path)
        conn.executescript('CREATE TABLE players (discord_user_id TEXT PRIMARY KEY NOT NULL, username TEXT NOT NULL, preferred_position TEXT NOT NULL, player_role TEXT NOT NULL, player_focus TEXT); INSERT INTO players VALUES ("1","Zak","ST","Advanced Forward",NULL);')
        conn.commit();conn.close()
        upgraded=Database(path)
        self.assertEqual(upgraded.rows('SELECT * FROM players')[0]['username'],'Zak')

    def test_partial_data_remains_null(self):
        mid=self.add(text='OurProClubs recap\nOpponent: Chelsea\nPossession: unavailable')[0]
        row=self.db.match(mid)
        self.assertIsNone(row['birmingham_score']); self.assertEqual(row['opponent'],'Chelsea')
        self.assertEqual(row['match_type'],'Unknown')

    async def test_friday_correct_time_and_once(self):
        await self.scheduler.tick(NOW-timedelta(minutes=1)); self.assertEqual(len(self.delivery.calls),0)
        await self.scheduler.tick(NOW); await self.scheduler.tick(NOW+timedelta(seconds=30))
        self.assertEqual(len(self.delivery.calls),1)

    def test_dst_times(self):
        winter=datetime(2026,1,9,13,tzinfo=UTC); summer=datetime(2026,7,10,12,tzinfo=UTC)
        self.assertEqual(friday_due(week_window(winter)[0]),winter)
        self.assertEqual(friday_due(week_window(summer)[0]),summer)

    async def test_missed_friday_restart(self):
        self.scheduler.seed(NOW-timedelta(days=1))
        restarted=WeeklyScheduler(Database(self.path),42,self.delivery)
        await restarted.tick(NOW+timedelta(hours=3));await restarted.tick(NOW+timedelta(hours=4))
        self.assertEqual(len(self.delivery.calls),1)

    async def test_crash_after_discord_acceptance_reconciles(self):
        self.scheduler.seed(NOW)
        job=self.db.rows('SELECT * FROM weekly_jobs')[0]
        self.delivery.messages[job['job_key']+':prompt']=123
        self.db.execute("UPDATE weekly_jobs SET state='sending',lease_until=?",((NOW-timedelta(seconds=1)).isoformat(),))
        await self.scheduler.tick(NOW)
        self.assertEqual(self.delivery.calls,[])
        self.assertEqual(self.db.rows('SELECT * FROM weekly_jobs')[0]['state'],'sent')

    async def test_delivery_failure_retries(self):
        self.delivery.fail=True;await self.scheduler.tick(NOW)
        self.delivery.fail=False;await self.scheduler.tick(NOW+timedelta(minutes=6))
        self.assertEqual(len(self.delivery.calls),1)

    async def test_skip_respected_after_restart(self):
        self.scheduler.seed(NOW)
        rid=self.db.rows('SELECT * FROM weekly_jobs')[0]['report_id']
        self.scheduler.skip(rid)
        await WeeklyScheduler(Database(self.path),42,self.delivery).tick(NOW+timedelta(hours=1))
        self.assertEqual(self.delivery.calls,[])
        self.assertEqual(self.db.report(rid)['status'],'skipped')

    async def test_reminder_one_report_and_one_delivery(self):
        await self.scheduler.tick(NOW)
        rid=self.db.rows('SELECT * FROM weekly_jobs')[0]['report_id']
        self.scheduler.remind(rid,NOW,minutes=1)
        await self.scheduler.tick(NOW+timedelta(seconds=59))
        self.assertEqual(len(self.delivery.calls),1)
        await self.scheduler.tick(NOW+timedelta(minutes=1));await self.scheduler.tick(NOW+timedelta(minutes=2))
        self.assertEqual(len(self.delivery.calls),2)
        self.assertEqual(len(self.db.rows('SELECT * FROM weekly_reports')),1)

    def test_generate_only_after_confirmation_no_publish(self):
        mid=self.add()[0]; self.db.classify(mid,'Official','Home',42);rid=self.report([mid])
        with self.assertRaises(ValueError): Reporter(self.db).generate(rid)
        self.db.confirm_report(rid); Reporter(self.db).generate(rid)
        self.assertEqual(self.db.report(rid)['status'],'draft')
        self.assertIsNone(self.db.report(rid)['draft_sent_at'])

    def test_unknown_warning_blocks_generation(self):
        a=self.add('1')[0];self.add('2');self.db.classify(a,'Official','Home',42)
        rid=self.report([a])
        with self.assertRaisesRegex(ValueError,'classification'): self.db.confirm_report(rid)

    def test_correction_invalidates_draft(self):
        mid=self.add()[0];self.db.classify(mid,'Official','Home',42);rid=self.report([mid])
        self.db.confirm_report(rid); Reporter(self.db).generate(rid)
        self.db.classify(mid,'Practice','Unknown',42)
        self.assertEqual(self.db.report(rid)['status'],'selecting')
        self.assertIsNone(self.db.report(rid)['article'])
        self.assertEqual(self.db.official_record()['played'],0)

    def test_metric_growth_and_development(self):
        ids=[]
        for i,(shots,passes,possession) in enumerate([(7,78,42),(10,82,49),(14,86,55)]):
            mid=self.add(str(i),at=f'2026-10-0{5+i}T22:00:00+00:00')[0];ids.append(mid)
            self.db.classify(mid,'Practice' if i<2 else 'Official','Unknown' if i<2 else 'Home',42)
            for metric,value in [('shots',shots),('passing',passes),('possession',possession)]:
                self.db.execute('INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,unit) VALUES (?,?,?,?,?,?)',(mid,'team','Birmingham City',metric,value,'count' if metric=='shots' else '%'))
        rid=self.report(ids);self.db.confirm_report(rid);article=Reporter(self.db).generate(rid)
        self.assertIn('7 to 10',article);self.assertIn('10 to 14',article)
        self.assertIn('FROM THE TRAINING GROUND',article)
        self.assertEqual(self.db.official_record()['played'],1)

    async def test_confirmed_article_sent_privately_for_review(self):
        bot=GafferBot(Config('test',42,30,database_path=self.path))
        mid=self.add()[0]; self.db.classify(mid,'Official','Home',42);rid=self.report([mid])
        owner=SimpleNamespace(send=AsyncMock())
        bot.fetch_user=AsyncMock(return_value=owner)
        interaction=SimpleNamespace(user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))
        button=next(c for c in ReportView(bot,rid).children if getattr(c,'label',None)=='Generate Report')
        await button.handler(interaction)
        owner.send.assert_awaited_once()
        self.assertIn('review only',owner.send.call_args.kwargs['content'])
        self.assertIsInstance(owner.send.call_args.kwargs['view'],DraftView)
        self.assertEqual(self.db.report(rid)['status'],'draft')
        self.assertIsNotNone(self.db.report(rid)['draft_sent_at'])
        await bot.close()

    async def test_shortened_schedule_before_production(self):
        self.scheduler.schedule_test(NOW)
        await self.scheduler.tick_tests(NOW+timedelta(seconds=59))
        self.assertEqual(self.delivery.calls,[])
        await self.scheduler.tick_tests(NOW+timedelta(minutes=1))
        await self.scheduler.tick_tests(NOW+timedelta(minutes=2))
        self.assertEqual(len(self.delivery.calls),1)
        self.assertTrue(self.delivery.calls[0][1].startswith('test:'))

    async def test_paged_selection_keeps_previous_pages(self):
        ids=[]
        for i in range(31):
            mid=self.add(str(i))[0];ids.append(mid)
            self.db.classify(mid,'Official' if i%2 else 'Practice','Home' if i%2 else 'Unknown',42)
        rid=self.report([ids[0]])
        self.db.replace_page_selection(rid,ids[20:],ids[20:22])
        self.assertEqual({m['match_id'] for m in self.db.selected(rid)},{ids[0],ids[20],ids[21]})
        bot=GafferBot(Config('test',42,30,database_path=self.path))
        self.assertTrue(ReportView(bot,rid,0).is_persistent())
        self.assertTrue(ReportView(bot,rid,1).is_persistent())
        await bot.close()

    def test_pep_recap_flag_takes_precedence(self):
        base={'GAFFER_DISCORD_TOKEN':'test','OWNER_DISCORD_USER_ID':'42','GAFFER_GUILD_ID':'30'}
        with patch.dict('os.environ',{**base,'PEP_FRIDAY_RECAP':'true'},clear=True):
            self.assertTrue(Config.load().schedule_enabled)
        with patch.dict('os.environ',{**base,'PEP_FRIDAY_RECAP':'false','GAFFER_FRIDAY_ENABLED':'true'},clear=True):
            self.assertFalse(Config.load().schedule_enabled)
        with patch.dict('os.environ',base,clear=True):
            self.assertFalse(Config.load().schedule_enabled)

    def test_registration(self):
        self.assertEqual(parse_registration('Pep, register me as a Striker with Advanced Forward role'),('Striker','Advanced Forward',None))
        self.assertEqual(parse_registration('Gaffer, register me as a Striker with Advanced Forward role'),('Striker','Advanced Forward',None))
        self.assertEqual(parse_registration('Gaffer, register me as a Striker with Advanced Forward role with Attack focus'),('Striker','Advanced Forward','Attack'))

    async def test_discord_views_commands_permissions_and_groups(self):
        bot=GafferBot(Config('test',42,30,database_path=self.path))
        a=self.add('1')[0];b=self.add('2')[0];self.add('3')
        self.db.classify(a,'Official','Home',42);self.db.classify(b,'Practice','Unknown',42)
        rid=self.report([a,b])
        view=ReportView(bot,rid)
        self.assertTrue(view.is_persistent())
        self.assertTrue(ReviewView(bot,a).is_persistent());self.assertTrue(DraftView(bot,rid).is_persistent())
        summary=bot.report_summary(rid)
        self.assertIn('OFFICIAL MATCHES',summary);self.assertIn('PRACTICE / DEVELOPMENT',summary)
        self.assertIn('1 matches still need classification',summary)
        self.assertFalse(bot.manager(SimpleNamespace(user=SimpleNamespace(id=999,roles=[]),guild_id=30)))
        self.assertTrue(bot.manager(SimpleNamespace(user=SimpleNamespace(id=42),guild_id=None)))
        commands={c.name for c in bot.tree.get_commands()}
        self.assertIn('configurepep',commands)
        self.assertNotIn('configuregaffer',commands)
        self.assertTrue({'status','matches','reviewmatches','match','weeklyreport','testweeklydm'}<=commands)
        await bot.close()

    async def test_listener_only_configured_source_and_duplicates(self):
        bot=GafferBot(Config('test',42,30,recap_channel_id=20,source_bot_id=99,database_path=self.path))
        msg=SimpleNamespace(id=1,guild=SimpleNamespace(id=30),channel=SimpleNamespace(id=20),author=SimpleNamespace(id=98),created_at=NOW,content='Birmingham City 2–1 Chelsea')
        await bot.ingest_message(msg);self.assertEqual(self.db.rows('SELECT * FROM matches'),[])
        msg.author.id=99;await bot.ingest_message(msg);await bot.ingest_message(msg)
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),1)
        await bot.close()

    async def test_empty_week_dm_summary(self):
        bot=GafferBot(Config('test',42,30,database_path=self.path))
        rid=self.db.open_report(*week_window(NOW),42)['report_id']
        self.assertIn('No classified matches available.',bot.report_summary(rid))
        await bot.close()


if __name__=='__main__':
    unittest.main()
