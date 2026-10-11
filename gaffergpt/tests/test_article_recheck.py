import json
import tempfile
import unittest
from pathlib import Path
from gaffergpt.database import Database,utcnow
from gaffergpt.weekly_intake import save_submission,content
from gaffergpt.reporter import Reporter
from gaffergpt.article_writer import period_label
from gaffergpt.report_verification import build_fact_sheet,ReportHold
from gaffergpt.recheck_article import ReviewedDraftRecheck


class RecheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Database(Path(self.tmp.name)/'test.db')
        self.report=self.db.open_report('2026-10-05T04:00:00+00:00','2026-10-12T04:00:00+00:00',42)
        self.rid=self.report['report_id']
        save_submission(self.db,self.rid,42,30,'2026-10-10 | Practice | FRESH CAKES FC | 2-5\n2026-10-10 | Practice | bandzwillmake | 3-3\n2026-10-10 | Practice | LittleD | 6-2\n2026-10-11 | Practice | Gougherton FC | 2-0')
        ids=[m['match_id'] for m in self.db.period_matches(self.report['week_start'],self.report['week_end'],True)]
        self.db.replace_page_selection(self.rid,ids,ids);self.db.confirm_report(self.rid)
        packet={'matches':self.db.selected(self.rid),'statistics':[],'management':content(self.db,self.rid),'period':period_label(self.report)}
        self.sheet=build_fact_sheet(packet)
        quote='In practice: a 2–5 defeat to FRESH CAKES FC, a 3–3 draw with bandzwillmake, a 6–2 victory over LittleD, and a 2–0 victory over Gougherton FC.'
        self.article={'title':'Contrasting practice results for Birmingham City','body':'Birmingham City’s practice fixtures produced a mixture of results.\n\n'+quote+'\n\nThe victory over LittleD and defeat against FRESH CAKES FC provided contrasting scorelines, with the draw against bandzwillmake and victory over Gougherton FC completing the results.'}
        self.evidence={'claims':[{'fact_id':k,'quote':quote} for k,f in self.sheet['facts'].items() if f['kind']=='fixture'],'unsupported':[]}
    def held(self,checks):
        attempt={'article':self.article,'checks':checks,'error':'Final numeric claims lack correctly attributed source evidence: result-list mapping','original_evidence':self.evidence}
        self.db.execute("INSERT INTO report_generation_audit(report_id,started_at,state,fact_sheet,attempts) VALUES (?,?,'held',?,?)",(self.rid,utcnow(),json.dumps(self.sheet),json.dumps([attempt])))
    def test_recheck_reuses_only_immutable_already_reviewed_prose(self):
        self.held(['editorial_review','deterministic_style'])
        article=Reporter(self.db,writer=ReviewedDraftRecheck(self.db,self.rid)).generate(self.rid)
        self.assertIn(self.article['body'],article)
        self.assertEqual(self.db.report(self.rid)['status'],'draft')
        latest=self.db.one('SELECT * FROM report_generation_audit ORDER BY audit_id DESC LIMIT 1')
        self.assertEqual(latest['state'],'passed')
        self.assertIn('final_recheck',json.loads(latest['verification'])['checks'])
    def test_no_editorial_pass_cannot_be_promoted(self):
        self.held(['deterministic_style'])
        with self.assertRaises(ReportHold):ReviewedDraftRecheck(self.db,self.rid)
    def test_changed_sources_cannot_reuse_editorial_review(self):
        self.held(['editorial_review','deterministic_style'])
        self.db.execute('UPDATE matches SET birmingham_score=9 WHERE match_id=1')
        with self.assertRaises(ReportHold):ReviewedDraftRecheck(self.db,self.rid)
