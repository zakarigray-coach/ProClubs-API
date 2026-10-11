import unittest
from gaffergpt.report_verification import build_fact_sheet,validate_final,ReportHold,digest


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
    def test_source_hash_remains_reproducible(self):
        s=self.sheet();value=s.pop('source_hash');self.assertEqual(value,digest(s))

if __name__=='__main__':unittest.main()

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
        self.assertEqual(len(writer.last_attempts),3)
        self.assertIsNone(writer.last_verification)
        self.assertLessEqual(writer.calls,10)
