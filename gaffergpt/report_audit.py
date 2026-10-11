"""Durable private verification history in Pep's existing SQLite database."""
import json
from .database import utcnow

SCHEMA='''CREATE TABLE IF NOT EXISTS report_generation_audit (
 audit_id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES weekly_reports(report_id),
 started_at TEXT NOT NULL, finished_at TEXT, state TEXT NOT NULL,
 source_hash TEXT, fact_sheet TEXT, attempts TEXT NOT NULL DEFAULT '[]',
 article_hash TEXT, verification TEXT, error TEXT
)'''


def start(db,report_id):
    with db.connect() as conn:
        conn.execute(SCHEMA)
        return conn.execute('INSERT INTO report_generation_audit(report_id,started_at,state) VALUES(?,?,?)',
                            (report_id,utcnow(),'running')).lastrowid


def finish(db,audit_id,writer,state,error=None):
    sheet=getattr(writer,'last_fact_sheet',None)
    proof=getattr(writer,'last_verification',None) or {}
    with db.connect() as conn:
        conn.execute('UPDATE report_generation_audit SET finished_at=?,state=?,source_hash=?,fact_sheet=?,attempts=?,article_hash=?,verification=?,error=? WHERE audit_id=?',
                     (utcnow(),state,(sheet or {}).get('source_hash'),json.dumps(sheet,ensure_ascii=False) if sheet else None,
                      json.dumps(getattr(writer,'last_attempts',[]),ensure_ascii=False),proof.get('article_hash'),json.dumps(proof,ensure_ascii=False),(str(error) or type(error).__name__)[:2000] if error is not None else None,audit_id))


def assert_current(db,report_id,sheet):
    """A passed draft cannot be delivered against subsequently changed source rows."""
    from .report_verification import ReportHold
    report=db.report(report_id)
    from .competitions import snapshot
    if snapshot(db,report_id)!=sheet.get('competition_context'):
        raise ReportHold('Competition details changed after verification. Generate a fresh checked article.')
    matches=[m for m in db.selected(report_id) if m['match_type'] in ('Official','Cup') or report['include_development']]
    by_id={m['match_id']:m for m in matches}
    if set(by_id)!={m['match_id'] for m in sheet['fixtures']}:
        raise ReportHold('The selected matches changed after this draft. Generate a fresh checked article before approval.')
    for fixture in sheet['fixtures']:
        row=by_id[fixture['match_id']]
        if any(row.get(k)!=fixture.get(k) for k in ('played_at','opponent','venue','competition','match_type','birmingham_score','opponent_score')):
            raise ReportHold('A selected fixture changed after this draft. Generate a fresh checked article before approval.')
        original=sheet['references'][f'match:{fixture["match_id"]}']
        if original.get('raw_recap')!=row.get('raw_recap'):
            raise ReportHold('A source recap changed after this draft. Generate a fresh checked article before approval.')
    keys=('match_id','subject_type','subject_key','metric','value','unit','source')
    prior=[tuple(row.get(k) for k in keys) for key,row in sheet['references'].items() if key.startswith('stat:')]
    current=[]
    for mid in by_id:
        current.extend(tuple(row.get(k) for k in keys) for row in db.rows('SELECT * FROM match_statistics WHERE match_id=?',(mid,)))
    if sorted(prior,key=repr)!=sorted(current,key=repr):
        raise ReportHold('Match statistics changed after this draft. Generate a fresh checked article before approval.')
    with db.connect() as conn:
        has_content=conn.execute("SELECT 1 FROM sqlite_master WHERE name='weekly_report_content'").fetchone()
        award=conn.execute('SELECT player_name,player_evidence FROM weekly_report_content WHERE report_id=?',(report_id,)).fetchone() if has_content else None
    old=sheet['references']['management:award']
    for key in ('player_name','player_evidence'):
        if (award[key] if award else None)!=old.get(key):
            raise ReportHold('The Player of the Week selection changed. Generate a fresh checked article before approval.')
