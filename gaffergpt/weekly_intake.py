"""Management supplies facts explicitly; intake never scrapes or guesses results."""
import hashlib
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .database import utcnow

CONTENT_SCHEMA = '''CREATE TABLE IF NOT EXISTS weekly_report_content (
 report_id INTEGER PRIMARY KEY REFERENCES weekly_reports(report_id) ON DELETE CASCADE,
 notes TEXT NOT NULL DEFAULT '', player_name TEXT NOT NULL DEFAULT '', player_evidence TEXT NOT NULL DEFAULT '',
 photo BLOB, photo_extension TEXT
)'''


def save_submission(db, report_id, actor, guild, results, notes='', player_name='', player_evidence=''):
    report=db.report(report_id)
    if not report or str(actor)!=report['owner_id']:
        raise ValueError('Only Coach can edit this report.')
    if report['status'] in ('approved','skipped'):
        raise ValueError('Reopen this report before editing it.')
    if bool(player_name.strip()) != bool(player_evidence.strip()):
        raise ValueError('Add both the featured player name and their factual achievement, or leave both blank.')
    parsed=[]; occurrences={}
    for line in results.splitlines():
        if not line.strip(): continue
        parts=[p.strip() for p in line.split('|')]
        if len(parts)!=4:
            raise ValueError('Each result needs: YYYY-MM-DD | Official Home, Official Away or Practice | Opponent | Birmingham score-Opponent score')
        day,kind,opponent,score=parts
        kinds={'official home':('Official','Home'),'official away':('Official','Away'),'practice':('Practice','Unknown'),'cup':('Cup','Unknown'),'cup home':('Cup','Home'),'cup away':('Cup','Away')}
        if kind.lower() not in kinds or not opponent or len(opponent)>100:
            raise ValueError('Use Official Home, Official Away or Practice and an opponent name.')
        try:
            played=datetime.strptime(day,'%Y-%m-%d').replace(hour=12,tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()
        except ValueError:
            raise ValueError('Use a real date in YYYY-MM-DD format.') from None
        if not report['week_start']<=played<report['week_end']:
            raise ValueError(f'{day} falls outside this reporting period.')
        match=re.fullmatch(r'(\d{1,2})\s*[-–]\s*(\d{1,2})',score)
        if not match: raise ValueError('Scores must be Birmingham first, such as 3-1.')
        own,other=map(int,match.groups()); match_type,venue=kinds[kind.lower()]
        canonical=f'{day}|{match_type}|{venue}|{opponent.casefold()}|{own}-{other}'
        occurrence=occurrences.get(canonical,0); occurrences[canonical]=occurrence+1
        source=f'manual:{report_id}:'+hashlib.sha256(canonical.encode()).hexdigest()
        parsed.append((source,occurrence,played,opponent,own,other,line,match_type,venue))
    from .competitions import report_event,set_match_details
    event=report_event(db,report_id)
    if any(row[-2]=='Cup' for row in parsed) and (not event or event['report_type']!='Cup'):
        raise ValueError('Select Cup / Tournament and its competition before adding cup results.')
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        current=conn.execute('SELECT status FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
        if current['status'] in ('approved','skipped'): raise ValueError('Reopen this report before editing it.')
        conn.execute(CONTENT_SCHEMA)
        conn.execute('INSERT INTO weekly_report_content(report_id,notes,player_name,player_evidence) VALUES(?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET notes=excluded.notes,player_name=excluded.player_name,player_evidence=excluded.player_evidence',(report_id,notes.strip(),player_name.strip(),player_evidence.strip()))
        added=0
        for source,part,played,opponent,own,other,raw,kind,venue in parsed:
            cur=conn.execute('''INSERT OR IGNORE INTO matches(source_message_id,source_channel_id,source_guild_id,source_part,detected_at,played_at,date_source,opponent,birmingham_score,opponent_score,raw_recap,match_type,venue,classification_status,counts_official,report_eligible,classified_by,classified_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'Classified',?,1,?,?)''',(source,'manual-weekly',str(guild),part,utcnow(),played,'management-date',opponent,own,other,raw,kind,venue,int(kind=='Official'),str(actor),utcnow()))
            added+=cur.rowcount
        conn.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id=?",(report_id,))
    from .competitions import report_event,set_match_details
    event=report_event(db,report_id)
    for source,part,*rest in parsed:
        row=db.one('SELECT * FROM matches WHERE source_message_id=? AND source_part=?',(source,part))
        if row['match_type']=='Cup':
            if not event or event['report_type']!='Cup':raise ValueError('Select Cup / Tournament and its competition before adding cup results.')
            set_match_details(db,row['match_id'],event['competition_key'],actor,'Coach confirmed cup result.')
    return added


def content(db, report_id):
    with db.connect() as conn:
        conn.execute(CONTENT_SCHEMA)
        row=conn.execute('SELECT * FROM weekly_report_content WHERE report_id=?',(report_id,)).fetchone()
        return dict(row) if row else {}


def save_photo(db, report_id, actor, data):
    report=db.report(report_id)
    if not report or str(actor)!=report['owner_id'] or report['status'] in ('approved','skipped'):
        raise ValueError('Only Coach can add a photo to an open report.')
    if len(data)>8*1024*1024: raise ValueError('Photo must be 8 MB or smaller.')
    extension='png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if data.startswith(b'\xff\xd8\xff') else 'webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None
    if not extension: raise ValueError('Attach a PNG, JPEG or WebP image.')
    with db.connect() as conn:
        conn.execute(CONTENT_SCHEMA)
        conn.execute('INSERT INTO weekly_report_content(report_id,photo,photo_extension) VALUES(?,?,?) ON CONFLICT(report_id) DO UPDATE SET photo=excluded.photo,photo_extension=excluded.photo_extension',(report_id,data,extension))
        conn.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id=?",(report_id,))
