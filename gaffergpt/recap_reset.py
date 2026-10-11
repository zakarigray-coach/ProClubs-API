"""Owner-authorized intake reset, preserving match history and scheduled jobs."""
import json
from .weekly_intake import CONTENT_SCHEMA

def reset_recap(db,report_id,owner,request):
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        marker='recap_reset:'+request
        if conn.execute('SELECT 1 FROM settings WHERE key=?',(marker,)).fetchone():return False
        report=conn.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
        if not report or report['owner_id']!=str(owner):raise ValueError('Report owner does not match.')
        if report['status'] in ('approved','skipped'):raise ValueError('Only an unfinished recap can be reset.')
        for row in conn.execute("SELECT key,value FROM settings WHERE key LIKE 'recap_preview:%'").fetchall():
            if json.loads(row['value']).get('report_id')==report_id:
                conn.execute('DELETE FROM settings WHERE key=?',(row['key'],))
        conn.execute('DELETE FROM settings WHERE key IN (?,?,?,?)',
                     (f'weekly_excel:{report_id}',f'weekly_excel_context:{report_id}','weekly_photo_awaiting','weekly_dm_awaiting'))
        conn.execute('DELETE FROM report_matches WHERE report_id=?',(report_id,))
        conn.execute(CONTENT_SCHEMA)
        conn.execute('DELETE FROM weekly_report_content WHERE report_id=?',(report_id,))
        conn.execute("UPDATE weekly_reports SET title=NULL,article=NULL,observations=NULL,status='selecting',confirmed_at=NULL,draft_sent_at=NULL WHERE report_id=?",(report_id,))
        conn.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)',('weekly_dm_awaiting',str(report_id)))
        conn.execute('INSERT INTO settings(key,value) VALUES (?,?)',(marker,'complete'))
    return True
