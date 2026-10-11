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
                      json.dumps(getattr(writer,'last_attempts',[]),ensure_ascii=False),proof.get('article_hash'),json.dumps(proof,ensure_ascii=False),str(error)[:2000] if error else None,audit_id))
