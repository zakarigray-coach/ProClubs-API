import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from gaffergpt.database import Database
from gaffergpt.parser import parse_recap,parse_registration,is_match_recap
from gaffergpt.reporter import Reporter
from gaffergpt.scheduler import week_window
from gaffergpt.config import Config
from gaffergpt.analysis import FactualGaffer, direction, tracking_text
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
    def test_recap_detection_preserves_partial_data(self):
        self.assertTrue(is_match_recap('PLAYER STATS\nStats unavailable'))
        self.assertTrue(is_match_recap('Opponent: Chelsea'))
        self.assertFalse(is_match_recap('Choose your club'))
        self.assertFalse(is_match_recap('Division 3 | Skill Rating: 1613'))

    def test_setup_cleanup_retains_records_and_leaves_real_matches(self):
        menu='<@42>, select a Club for Automode:'
        bad=self.add('menu',menu)[0]
        partial=self.add('partial','PLAYER STATS\nStats unavailable')[0]
        real=self.add('real')[0]
        classified=self.add('classified','<@42>, select a Club to view members for:')[0]
        self.db.classify(classified,'Practice','Unknown',42)
        self.db.ingest('other',21,30,NOW.isoformat(),menu,parse_recap(menu))
        self.assertEqual(self.db.ignore_setup_prompts(20,30,42),[bad])
        self.assertEqual(self.db.ignore_setup_prompts(20,30,42),[])
        row=self.db.match(bad)
        self.assertEqual((row['match_type'],row['counts_official'],row['report_eligible']),('Ignored',0,0))
        self.assertEqual(row['raw_recap'],menu)
        self.assertEqual(self.db.match(partial)['match_type'],'Unknown')
        self.assertEqual(self.db.match(real)['match_type'],'Unknown')
        self.assertEqual(self.db.match(classified)['match_type'],'Practice')
        self.assertEqual(len(self.db.rows('SELECT * FROM matches')),5)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'gaffergpt.db')
        self.db=Database(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, message='1', text='Birmingham City 2–1 Chelsea', at='2026-10-06T22:00:00+00:00'):
        return self.db.ingest(message,20,30,at,text,parse_recap(text))

    def report(self,ids):
        r=self.db.open_report(*week_window(NOW),42)
        self.db.replace_page_selection(r['report_id'],ids,ids)
        return r['report_id']

    def test_link_preserves_registration_and_restart(self):
        self.db.register_player(42,'coach','CAM','Playmaker','Attack')
        self.db.link_player(42,'coach','DaddyGray10420',42)
        reopened=Database(self.path)
        self.assertEqual(reopened.player_link(42)['player_name'],'DaddyGray10420')
        self.assertEqual(reopened.one('SELECT * FROM players')['preferred_position'],'CAM')

    def test_link_unique_normalized_and_atomic(self):
        self.db.link_player(42,'coach','DaddyGray10420',42)
        self.db.link_player(43,'other','Another Name',43)
        with self.assertRaises(ValueError):
            self.db.link_player(43,'other','  daddygray10420  ',43)
        self.assertEqual(self.db.player_link(43)['player_name'],'Another Name')
        self.db.link_player(42,'coach','NewName',42)
        self.db.link_player(43,'other','DaddyGray10420',42)
        self.assertEqual(self.db.player_link(43)['linked_by'],'42')

    def test_unlink_keeps_stats_and_can_reassign(self):
        mid=self.add()[0]
        self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES (?,'player','DaddyGray10420','rating',6.4)",(mid,))
        self.db.link_player(42,'coach','DaddyGray10420',42)
        self.db.unlink_player(42)
        self.db.link_player(43,'other','DaddyGray10420',42)
        self.assertEqual(len(self.db.rows('SELECT * FROM match_statistics')),1)

    def test_invalid_player_name(self):
        for name in ('', '   ', 'x'*81, 'bad\x00name'):
            with self.assertRaises(ValueError):
                self.db.link_player(42,'coach',name,42)

    def stats_text(self,score='MPL BIRMINGHAM 1-3 AMADNESS FC'):
        return score+'\nMatch Type: League Match\nPLAYER STATS\nDaddyGray10420 — Attacking Magician\nRAT: 6.4 | GLS: - | SHT: 1 | AST: - | 2AST: 1\nPAS: 14/19 | POS: 3/3 | TKL: 2/9\nOther Player — Midfield Boss\nRAT: 7.5 | PAS: 9/10\nTEAM STATS\nFINAL SCORE\nMPL Birmingham 1\nAmadness FC 3'

    def test_ambiguous_multimatch_stats_not_assigned(self):
        text=self.stats_text('MPL Birmingham 1-3 Amadness FC\nAmadness FC 2-2 MPL Birmingham')
        ids=self.add(text=text)
        self.assertEqual(len(ids),2)
        self.assertEqual(self.db.rows('SELECT * FROM match_statistics'),[])

    def test_partial_invalid_stats_and_zero(self):
        text=self.stats_text().replace('RAT: 6.4','RAT: 16.4').replace('PAS: 14/19','PAS: 1.5/19').replace('SHT: 1','SHT: 0')
        mid=self.add(text=text)[0]
        stats={r['metric']:r['value'] for r in self.db.rows("SELECT * FROM match_statistics WHERE subject_key='DaddyGray10420'")}
        self.assertNotIn('rating',stats)
        self.assertNotIn('passes_completed',stats)
        self.assertEqual(stats['shots'],0)
        self.assertNotIn('goals',stats)

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

    def test_trend_direction_not_always_more_is_better(self):
        self.assertEqual(direction('shots',[7,10,14]),'improving')
        self.assertEqual(direction('goals_conceded',[3,2,1]),'improving')
        self.assertEqual(direction('shots',[10,7,9]),'mixed')
        self.assertEqual(direction('rating',[7,7,7]),'steady')
        self.assertEqual(direction('dri',[5,6,7]),'increasing')

    def test_three_practice_trend_and_official_separate(self):
        ids=[]
        for index,value in enumerate([7,10,14,20]):
            mid=self.add(str(index),at=f'2026-10-0{5+index}T22:00:00+00:00')[0];ids.append(mid)
            self.db.classify(mid,'Practice' if index<3 else 'Official','Home',42)
            self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,unit) VALUES (?,'team','Birmingham City','shots',?,'count')",(mid,value))
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],self.db.rows('SELECT * FROM match_statistics'))
        trend=next(t for t in obs['trends'] if t['metric']=='shots')
        self.assertEqual(trend['values'],[7,10,14])
        self.assertEqual(trend['match_type'],'Practice')
        self.assertEqual(trend['direction'],'improving')
        self.assertIn('Practice to official',tracking_text(obs))

    def test_trends_never_cross_units_or_opponents(self):
        ids=[]
        for index in range(3):
            mid=self.add(str(index),text='Birmingham City 2-1 '+('Arsenal' if index==2 else 'Chelsea'))[0];ids.append(mid)
            self.db.classify(mid,'Practice','Unknown',42)
            self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,unit) VALUES (?,'team','Birmingham City','passing',80,?)",(mid,'%' if index==0 else 'count'))
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],self.db.rows('SELECT * FROM match_statistics'))
        self.assertFalse(any(t['metric']=='passing' for t in obs['trends']))
        self.assertFalse(any(c['metric']=='passing' for c in obs['comparisons']))

    def test_doubleheader_eastern_date_preserves_two_matches(self):
        ids=[]
        for index,(venue,at) in enumerate([('Home','2026-10-07T03:30:00+00:00'),('Away','2026-10-07T04:00:00+00:00')]):
            mid=self.add(str(index),at=at)[0];ids.append(mid)
            self.db.classify(mid,'Official',venue,42,'MPL')
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],[])
        self.assertEqual(obs['doubleheaders'],[])  # 11:30pm and midnight ET are separate dates.
        self.db.execute('UPDATE matches SET played_at=? WHERE match_id=?',('2026-10-07T03:59:00+00:00',ids[1]))
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],[])
        self.assertEqual(obs['doubleheaders'][0]['match_ids'],ids)
        self.assertEqual(obs['summaries']['Official']['scored_matches'],2)

    def test_derived_ratios_skip_zero_and_missing_denominators(self):
        ids=[]
        for index in range(3):
            mid=self.add(str(index))[0];ids.append(mid);self.db.classify(mid,'Practice','Unknown',42)
            for metric,value in [('passes_completed',index+1),('passes_attempted',10)]:
                self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES (?,'team','Birmingham City',?,?)",(mid,metric,value))
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],self.db.rows('SELECT * FROM match_statistics'))
        trend=next(t for t in obs['trends'] if t['metric']=='pass_completion')
        self.assertEqual(trend['values'],[10,20,30])
        self.assertEqual(trend['unit'],'%')

    def test_development_excludes_individual_stats(self):
        ids=[]
        for index in range(3):
            mid=self.add(str(index))[0];ids.append(mid);self.db.classify(mid,'Practice','Unknown',42)
            self.db.execute("INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value) VALUES (?,'player','DaddyGray10420','rating',?)",(mid,6+index))
        obs=FactualGaffer().analyze([self.db.match(i) for i in ids],self.db.rows('SELECT * FROM match_statistics'))
        self.assertTrue(all(t['subject_type']=='team' for t in obs['trends']))
        self.assertTrue(all(c['subject_type']=='team' for c in obs['comparisons']))
        self.assertNotIn('DaddyGray10420',tracking_text(obs))
        rid=self.report(ids);self.db.confirm_report(rid)
        self.assertNotIn('DaddyGray10420',Reporter(self.db).generate(rid))
        self.assertEqual(len(self.db.rows('SELECT * FROM match_statistics')),3)

    def test_report_development_disabled_and_unselected_excluded(self):
        practice=self.add('practice',text='Birmingham City 9-0 Chelsea')[0];self.db.classify(practice,'Practice','Unknown',42)
        official=self.add('official',text='Birmingham City 2-1 Chelsea')[0];self.db.classify(official,'Official','Home',42)
        unselected=self.add('unselected',text='Birmingham City 8-0 Arsenal')[0];self.db.classify(unselected,'Official','Away',42)
        rid=self.report([practice,official]);self.db.execute('UPDATE weekly_reports SET include_development=0 WHERE report_id=?',(rid,))
        self.db.confirm_report(rid);article=Reporter(self.db).generate(rid)
        self.assertIn('1 win from 1 selected',article)
        self.assertNotIn('9–0',article)
        self.assertNotIn('Arsenal',article)
        self.assertNotIn('FROM THE TRAINING GROUND',article)
        self.assertNotIn('Practice',article)
        self.assertIn('has not been published',article)

    async def test_confirmed_article_sent_privately_for_review(self):
        from unittest.mock import patch,AsyncMock
        media_patch=patch('gaffergpt.bot.report_attachments',AsyncMock(return_value=[]))
        media_patch.start();self.addCleanup(media_patch.stop)
        text_patch=patch('gaffergpt.bot.send_checked_article',AsyncMock())
        text_patch.start();self.addCleanup(text_patch.stop)
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

    def test_registration(self):
        self.assertEqual(parse_registration('Pep, register me as a Striker with Advanced Forward role'),('Striker','Advanced Forward',None))
        self.assertEqual(parse_registration('Gaffer, register me as a Striker with Advanced Forward role'),('Striker','Advanced Forward',None))
        self.assertEqual(parse_registration('Gaffer, register me as a Striker with Advanced Forward role with Attack focus'),('Striker','Advanced Forward','Attack'))

    async def test_empty_week_dm_summary(self):
        bot=GafferBot(Config('test',42,30,database_path=self.path))
        rid=self.db.open_report(*week_window(NOW),42)['report_id']
        self.assertIn('No classified matches available.',bot.report_summary(rid))
        await bot.close()


if __name__=='__main__':
    unittest.main()
