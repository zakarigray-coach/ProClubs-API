"""Recheck immutable, already edited prose after a source-matching correction."""
import json
from .article_writer import check_finished_prose,check_feature_quality,feature_facts
from .report_verification import build_fact_sheet,validate_final,source_identity,ReportHold
from .report_audit import assert_current


class ReviewedDraftRecheck:
    """Uses the existing Reporter transaction; no new prose and no provider call."""
    def __init__(self,db,report_id):
        audit=db.one("SELECT * FROM report_generation_audit WHERE report_id=? AND state='held' ORDER BY audit_id DESC LIMIT 1",(report_id,))
        if not audit or not audit['fact_sheet']:raise ReportHold('No completed held source review is available.')
        self.source=json.loads(audit['fact_sheet']);assert_current(db,report_id,self.source)
        self.candidates=[]
        for attempt in reversed(json.loads(audit['attempts'])):
            if not {'editorial_review','deterministic_style'}<=set(attempt.get('checks',[])):continue
            if not attempt.get('original_evidence'):continue
            if not str(attempt.get('error','')).startswith(('Final numeric claims lack correctly attributed source evidence','Fixture claim names the wrong opponent')):continue
            self.candidates.append(attempt)
        if not self.candidates:raise ReportHold('This draft has no already-passed editorial review with a recoverable source reference. Normal generation is required.')
        self.audit_id=audit['audit_id']
        self.reset_audit()

    def reset_audit(self):
        self.last_fact_sheet=None;self.last_verification=None;self.last_attempts=[]

    def write(self,packet):
        sheet=build_fact_sheet(packet);self.last_fact_sheet=sheet
        if source_identity(sheet)!=source_identity(self.source):
            raise ReportHold('Sources changed after the editorial review. Generate a fresh draft.')
        clean=dict(packet)
        clean['observations']=dict(packet.get('observations',{}),player_statistics={k:g['players'] for k,g in sheet['groups'].items()})
        for attempt in self.candidates:
            article=attempt['article'];evidence=attempt['original_evidence']
            try:
                check_finished_prose(article,feature_facts(clean))
                check_feature_quality(article,clean)
                proof=validate_final(article,sheet,evidence)
            except ValueError as error:
                self.last_attempts.append({'state':'recheck_held','error':str(error),'prior_audit_id':self.audit_id})
                continue
            proof['checks']+=['deterministic_style','editorial_review','final_recheck']
            proof['evidence']=evidence;proof['prior_editorial_audit_id']=self.audit_id
            self.last_verification=proof
            self.last_attempts.append({'state':'passed','article':article,'checks':proof['checks'],
                                       'prior_audit_id':self.audit_id,'immutable_editorial_reuse':True})
            return article['title'],article['body']
        raise ReportHold('The saved prose still fails current source checks. It remains held.')
