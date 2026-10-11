import unittest
from gaffergpt.report_verification import build_fact_sheet,validate_final,ReportHold,digest,source_identity


def fixture(mid,kind='Practice',opponent='Chelsea',own=2,other=1):
    return dict(match_id=mid,match_type=kind,opponent=opponent,birmingham_score=own,
                opponent_score=other,venue='Home',competition=None,played_at=f'2026-10-{mid:02d}T20:00:00+00:00',raw_recap='Original recap')

def stat(mid,name,metric,value,source='PCT+ Excel'):
    return dict(match_id=mid,subject_type='player',subject_key=name,metric=metric,value=value,source=source)

class VerificationTests(unittest.TestCase):
    def sheet(self,matches=None,stats=None,**kw):
        return build_fact_sheet(dict(matches=matches or [fixture(1)],statistics=stats or [],**kw))
    def evidence(self,sheet,subject,metric,quote,kind='player',classification='Practice',fixture_id=None):
        key=next(k for k,f in sheet['facts'].items() if f['subject']==subject and f['metric']==metric and f['kind']==kind and f['classification']==classification and f['fixture_id']==fixture_id)
        return {'fact_id':key,'quote':quote}
    def validate(self,sheet,body,claims):
        return validate_final({'title':'Birmingham review practice results','body':body},sheet,{'claims':claims,'unsupported':[]})
    def test_two_fixtures_same_opponent_remain_separate(self):
        s=self.sheet([fixture(1,'Official'),fixture(2,'Official',own=1,other=3)])
        self.assertEqual(len(s['fixtures']),2)
        self.assertEqual(s['groups']['Official']['summary'],dict(matches=2,wins=1,draws=0,losses=1,goals_for=3,goals_against=4))
    def test_mixed_scopes_calculated_separately(self):
        s=self.sheet([fixture(1),fixture(2,'Official')],[stat(1,'Zak','goals',7),stat(2,'Zak','goals',1)])
        self.assertEqual(s['groups']['Practice']['players'][0]['goals'],7)
        self.assertEqual(s['groups']['Official']['players'][0]['goals'],1)
        text='In league fixtures, Zak scored seven goals.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Zak','goals',text)])
    def test_conflicting_source_values_hold(self):
        with self.assertRaisesRegex(ReportHold,'Conflicting goals'):
            self.sheet(stats=[stat(1,'Zak','goals',1),stat(1,'Zak','goals',2,'OurProClubs')])
    def test_conflicting_cached_totals_hold(self):
        with self.assertRaisesRegex(ReportHold,'conflicts'):
            self.sheet(observations={'summaries':{'Practice':{'goals_for':99}}})
    def test_missing_stat_not_treated_as_zero_or_full_total(self):
        s=self.sheet([fixture(1),fixture(2)],[stat(1,'Zak','goals',2),stat(2,'Zak','rating',8)])
        self.assertFalse(any(f['metric']=='goals' and f['fixture_id'] is None for f in s['facts'].values()))
        self.assertTrue(s['warnings'])
    def test_impossible_ratio_holds(self):
        with self.assertRaises(ReportHold):self.sheet(stats=[stat(1,'Zak','shots',1),stat(1,'Zak','shots_on_target',2)])
    def test_high_scoring_player_mixed_results(self):
        s=self.sheet([fixture(1,own=2,other=5),fixture(2,own=6,other=2)],
                     [stat(1,'TraapxLit','goals',3),stat(2,'TraapxLit','goals',4)])
        text='TraapxLit scored seven goals in practice.'
        proof=self.validate(s,text,[self.evidence(s,'TraapxLit','goals',text)])
        self.assertIn('numeric_coverage',proof['checks'])
        self.assertEqual(s['groups']['Practice']['summary']['losses'],1)
    def test_award_pronoun_resolves_only_unambiguous_player(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',1),stat(1,'Other','goals',1)],management={'player_name':'Zak','player_evidence':'Confirmed'})
        key=next(k for k,f in s['facts'].items() if f['kind']=='award')
        quote='He was named Birmingham City’s Player of the Week.'
        self.validate(s,'Zak featured in practice. '+quote,[{'fact_id':key,'quote':quote}])
        for prefix in ('Other featured in practice. ','Zak and Other featured in practice. '):
            with self.assertRaises(ValueError):self.validate(s,prefix+quote,[{'fact_id':key,'quote':quote}])
    def test_wrong_player_even_when_number_exists_is_rejected(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',7),stat(1,'Other','goals',3)])
        text='Other scored seven goals in practice.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Zak','goals',text)])
    def test_wrong_metric_even_when_number_exists_is_rejected(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',3),stat(1,'Zak','assists',7)])
        text='Zak recorded 3 assists and 7 goals in practice.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Zak','goals',text),self.evidence(s,'Zak','assists',text)])
    def test_individual_match_stat_cannot_cover_period_total(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',2)])
        text='Zak scored two goals across the practice week.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Zak','goals',text,fixture_id=1)])
    def test_per_fixture_stat_requires_opponent(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',2)])
        text='Zak scored two goals against Chelsea in practice.'
        self.validate(s,text,[self.evidence(s,'Zak','goals',text,fixture_id=1)])
    def test_wrong_score_and_result_rejected(self):
        s=self.sheet()
        for text in ('Birmingham lost 2–1 against Chelsea in practice.','Birmingham won 4–1 against Chelsea in practice.'):
            with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Chelsea','score',text,kind='fixture',fixture_id=1)])
    def test_unselected_name_leak_and_wrong_case_rejected(self):
        s=self.sheet(stats=[stat(1,'TraapxLit','goals',7)],excluded_names=['Arsenal'])
        for text in ('Birmingham played Arsenal.','traapxlit played well.'):
            with self.assertRaises(ValueError):self.validate(s,text,[])
    def test_quotes_and_chronology_rejected(self):
        s=self.sheet()
        for text in ('A late winner lifted Birmingham.','Birmingham mounted a comeback.','Zak said "Great win".'):
            with self.assertRaises(ValueError):self.validate(s,text,[])
    def test_review_pass_cannot_replace_numeric_evidence(self):
        with self.assertRaises(ValueError):self.validate(self.sheet(),'Birmingham scored 99 goals.',[])
    def test_team_total_cannot_be_used_as_player_goals(self):
        s=self.sheet(stats=[stat(1,'Zak','goals',1)])
        text='Zak scored two goals in practice.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Birmingham City','goals_for',text,kind='team')])
    def test_reversed_score_requires_away_opponent_first(self):
        match=fixture(1,'Official');match['venue']='Away';s=self.sheet([match])
        text='Birmingham City 1–2 Chelsea in an official fixture.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Chelsea','score',text,kind='fixture',classification='Official',fixture_id=1)])
    def test_written_count_with_classification_cannot_escape_check(self):
        with self.assertRaises(ValueError):self.validate(self.sheet(),'Birmingham played seven practice fixtures.',[])
    def test_separate_same_opponent_stat_requires_fixture_identity(self):
        s=self.sheet([fixture(1,'Official'),fixture(2,'Official',own=1,other=3)], [stat(1,'Zak','goals',2),stat(2,'Zak','goals',1)])
        text='Zak scored two goals against Chelsea in official matches.'
        with self.assertRaises(ValueError):self.validate(s,text,[self.evidence(s,'Zak','goals',text,classification='Official',fixture_id=1)])
    def test_fixture_dates_and_daily_count_have_source_references(self):
        s=self.sheet([fixture(1,opponent='Chelsea'),dict(fixture(2,opponent='Arsenal'),played_at='2026-10-01T20:00:00+00:00')])
        text='Birmingham played two practice fixtures on 1 October.'
        day=next(k for k,f in s['facts'].items() if f['kind']=='schedule')
        self.validate(s,text,[{'fact_id':day,'quote':text}])
        for text in ('Birmingham played three practice fixtures on 1 October.','Birmingham played two official fixtures on 1 October.'):
            with self.assertRaises(ValueError):self.validate(s,text,[{'fact_id':day,'quote':text}])
    def test_message_timestamp_does_not_become_verified_match_day(self):
        s=self.sheet([dict(fixture(1),date_source='message')])
        self.assertFalse(any(f['kind'] in ('date','schedule') for f in s['facts'].values()))
    def test_not_league_does_not_misclassify_practice_claim(self):
        s=self.sheet([fixture(1,own=7)],[stat(1,'Zak','goals',7)])
        text='Zak scored seven goals in practice, not league fixtures.'
        self.validate(s,text,[self.evidence(s,'Zak','goals',text)])
    def test_derived_fact_changes_do_not_change_source_identity(self):
        s=self.sheet();old=s['source_hash'];s['facts']['extra']={'kind':'comparison','value':True}
        self.assertEqual(source_identity(s),old)
    def test_leading_scorer_only_when_unrecorded_goals_cannot_overtake(self):
        s=self.sheet([fixture(1,own=8)],[stat(1,'Zak','goals',7),stat(1,'Other','goals',1)])
        self.assertTrue(any(f['kind']=='comparison' and f['subject']=='Zak' for f in s['facts'].values()))
        s=self.sheet([fixture(1,own=20)],[stat(1,'Zak','goals',7),stat(1,'Other','goals',1)])
        self.assertFalse(any(f['kind']=='comparison' for f in s['facts'].values()))
    def test_goal_contributions_are_calculated_and_not_repeated(self):
        s=self.sheet([fixture(1,own=10)],[stat(1,'Zak','goals',7),stat(1,'Zak','assists',2)])
        text='Zak scored seven goals and two assists, a 9-goal direct contribution in practice.'
        claims=[self.evidence(s,'Zak',m,text) for m in ('goals','assists','goal_contributions')]
        with self.assertRaisesRegex(ValueError,'combined'):self.validate(s,text,claims)
    def test_source_hash_remains_reproducible(self):
        s=self.sheet();value=s.pop('source_hash');self.assertEqual(value,source_identity(s))


class AuditTests(unittest.TestCase):
    def test_failed_review_and_source_reference_are_stored(self):
        import tempfile,json
        from types import SimpleNamespace
        from pathlib import Path
        from gaffergpt.database import Database
        from gaffergpt import report_audit
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'pep.db')
            with db.connect() as conn:
                rid=conn.execute("INSERT INTO weekly_reports(week_start,week_end,owner_id,created_at) VALUES('2026-10-05','2026-10-12','42','2026-10-11')").lastrowid
            aid=report_audit.start(db,rid)
            writer=SimpleNamespace(last_fact_sheet=build_fact_sheet({'matches':[fixture(1)]}),last_verification=None,last_attempts=[{'state':'rejected','error':'Wrong attribution'}])
            report_audit.finish(db,aid,writer,'held','No finished article delivered')
            db=Database(Path(folder)/'pep.db')
            row=db.rows('SELECT * FROM report_generation_audit')[0]
            self.assertEqual(row['state'],'held')
            self.assertEqual(json.loads(row['fact_sheet'])['references']['match:1']['raw_recap'],'Original recap')
            self.assertEqual(json.loads(row['attempts'])[0]['error'],'Wrong attribution')
    def test_changed_source_blocks_delivery_and_approval(self):
        import tempfile
        from pathlib import Path
        from gaffergpt.database import Database
        from gaffergpt.parser import parse_recap
        from gaffergpt.report_audit import assert_current
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'pep.db')
            text='Birmingham City 2–1 Chelsea'
            mid=db.ingest('123',20,30,'2026-10-06T22:00:00+00:00',text,parse_recap(text))[0]
            db.classify(mid,'Practice','Unknown',42)
            rid=db.open_report('2026-10-05','2026-10-12',42)['report_id']
            db.replace_page_selection(rid,[mid],[mid])
            sheet=build_fact_sheet({'matches':db.selected(rid)})
            assert_current(db,rid,sheet)
            db.execute('UPDATE matches SET birmingham_score=3 WHERE match_id=?',(mid,))
            with self.assertRaisesRegex(ReportHold,'fixture changed'):assert_current(db,rid,sheet)
    def test_bounded_retries_never_return_failed_article(self):
        import json
        from gaffergpt.article_writer import SportsWriter
        class RejectingWriter(SportsWriter):
            calls=0
            async def advise(self,analysis,formation=''):
                self.calls+=1
                return json.dumps({'title':'Birmingham review','body':'Those the results. '*20})
        writer=RejectingWriter('test')
        with self.assertRaisesRegex(RuntimeError,'three revision'):
            writer.write({'matches':[fixture(1)],'statistics':[]})
        self.assertEqual(sum(a.get('state')=='rejected' for a in writer.last_attempts),3)
        self.assertIsNone(writer.last_verification)
        self.assertLessEqual(writer.calls,10)

class RecoveryTests(unittest.TestCase):
    def test_recovery_requires_matching_source_and_reruns_reviews(self):
        import json
        from gaffergpt.article_writer import SportsWriter
        packet={'matches':[fixture(1)],'statistics':[]}
        article={'title':'Birmingham review the practice programme','body':'Birmingham’s practice programme offers the club a chance to assess its football away from league competition. The review focuses on the selected fixture and the recorded result. That distinction gives the training session its proper context while keeping the competitive record separate.'}
        class Writer(SportsWriter):
            def __init__(self):super().__init__('test');self.calls=[]
            async def advise(self,analysis,formation=''):
                r=json.loads(analysis);self.calls.append(r)
                if r.get('desk_task')=='audit_finished_article':return json.dumps({'title':'PASS','body':''})
                if r.get('desk_task')=='locate_final_claims':return json.dumps({'claims':[],'unsupported':[]})
                return json.dumps(article)
        for matching in (True,False):
            source=build_fact_sheet(packet)['source_hash'] if matching else 'obsolete-source'
            writer=Writer();writer.write(dict(packet,recovery={'source_hash':source,'article':article,'error':'Correct the headline.'}))
            self.assertEqual(len(writer.calls),3 if matching else 4)
            self.assertTrue(writer.last_verification)
            self.assertEqual(sum(a.get('state')=='recovered' for a in writer.last_attempts),int(matching))
            self.assertTrue(any(c.get('desk_task')=='audit_finished_article' for c in writer.calls))
            self.assertTrue(any(c.get('desk_task')=='locate_final_claims' for c in writer.calls))

class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_article_cannot_reuse_passed_audit(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from gaffergpt.database import Database
        from gaffergpt import report_audit
        from gaffergpt.bot import DraftView
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'pep.db')
            rid=db.open_report('2026-10-05','2026-10-12',42)['report_id']
            original={'title':'Original headline','body':'Original checked text.'}
            db.execute("UPDATE weekly_reports SET status='draft',title=?,article=? WHERE report_id=?",(original['title'],'RT FOOTBALL MEDIA\n\nChanged text.',rid))
            aid=report_audit.start(db,rid)
            writer=SimpleNamespace(last_fact_sheet=build_fact_sheet({'matches':[]}),last_attempts=[],last_verification={'article_hash':digest(original),'checks':['editorial_review']})
            report_audit.finish(db,aid,writer,'passed')
            bot=SimpleNamespace(db=db,config=SimpleNamespace(owner_id=42))
            interaction=SimpleNamespace(user=SimpleNamespace(id=42),response=SimpleNamespace(send_message=AsyncMock()))
            button=next(b for b in DraftView(bot,rid).children if b.label=='Approve Draft (save only)')
            await button.callback(interaction)
            self.assertEqual(db.report(rid)['status'],'draft')
            self.assertIn('changed after verification',interaction.response.send_message.call_args.args[0])
            self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])

if __name__=='__main__':unittest.main()
