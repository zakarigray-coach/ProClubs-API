"""Explicit event metadata, isolated cup totals and safe legacy migrations."""
import json
import sqlite3
from datetime import date
from pathlib import Path
from .database import utcnow

SCHEMA='''
CREATE TABLE IF NOT EXISTS competitions (
 competition_key TEXT PRIMARY KEY, name TEXT NOT NULL,
 report_type TEXT NOT NULL CHECK(report_type IN ('League','Cup','Practice')),
 event_start TEXT, event_end TEXT, format TEXT, start_time TEXT, prizes TEXT
);
CREATE TABLE IF NOT EXISTS report_competitions (
 report_id INTEGER PRIMARY KEY REFERENCES weekly_reports(report_id),
 competition_key TEXT NOT NULL REFERENCES competitions(competition_key),
 outcome TEXT NOT NULL DEFAULT 'Unknown' CHECK(outcome IN ('Unknown','Advanced','Eliminated','Champions','Still competing')),
 outcome_evidence TEXT, award_label TEXT NOT NULL DEFAULT 'Cup Standout', award_scope TEXT
);
CREATE TABLE IF NOT EXISTS cup_match_details (
 match_id INTEGER PRIMARY KEY REFERENCES matches(match_id),
 competition_key TEXT NOT NULL REFERENCES competitions(competition_key),
 stage TEXT, group_bracket TEXT, tie_key TEXT, leg INTEGER CHECK(leg IN (1,2)),
 extra_time_for INTEGER CHECK(extra_time_for>=0), extra_time_against INTEGER CHECK(extra_time_against>=0),
 penalties_for INTEGER CHECK(penalties_for>=0), penalties_against INTEGER CHECK(penalties_against>=0),
 evidence TEXT NOT NULL
);
'''


def initialise(db):
    """Copy constrained tables atomically, preserving IDs and every child reference."""
    from .database import SCHEMA as main_schema
    with db.connect() as conn:
        match_sql=conn.execute("SELECT sql FROM sqlite_master WHERE name='matches'").fetchone()[0]
        columns={r['name'] for r in conn.execute('PRAGMA table_info(weekly_reports)')}
        needs_matches="'Cup'" not in match_sql
        needs_reports='report_key' not in columns
    if needs_matches or needs_reports:
        backup=Path(db.path+'.pre-cup.bak')
        if not backup.exists():
            with sqlite3.connect(db.path) as source, sqlite3.connect(backup) as target:
                source.backup(target)
        conn=sqlite3.connect(db.path,timeout=15)
        try:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute('BEGIN IMMEDIATE')
            for table,needed in [('matches',needs_matches),('weekly_reports',needs_reports)]:
                if not needed:continue
                old=[r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
                definition=main_schema.split(f'CREATE TABLE IF NOT EXISTS {table} (',1)[1].split('\n);',1)[0]
                conn.execute(f'CREATE TABLE {table}_cup_migration ('+definition+'\n)')
                fields=','.join(old)
                conn.execute(f'INSERT INTO {table}_cup_migration ({fields}) SELECT {fields} FROM {table}')
                conn.execute(f'DROP TABLE {table}')
                conn.execute(f'ALTER TABLE {table}_cup_migration RENAME TO {table}')
            conn.execute('CREATE INDEX IF NOT EXISTS matches_by_date ON matches(played_at)')
            if conn.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Cup migration would break database references; changes rolled back.')
            conn.commit()
        except Exception:
            conn.rollback();raise
        finally:conn.close()
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO competitions(competition_key,name,report_type) VALUES ('mpl-league','MPL League','League')")
        conn.execute("INSERT OR IGNORE INTO competitions(competition_key,name,report_type) VALUES ('practice','Practice / Friendly','Practice')")
        conn.execute("INSERT OR IGNORE INTO competitions(competition_key,name,report_type,event_start,event_end) VALUES ('mpl-pre-season-cup-2026','The Minglewood Cup','Cup','2026-10-13','2026-10-15')")
        conn.execute("UPDATE competitions SET name='The Minglewood Cup',event_end='2026-10-15',format='Single elimination; preseason tournament ahead of Season 4',start_time='22:00 EST as announced; timezone interpretation unconfirmed' WHERE competition_key='mpl-pre-season-cup-2026' AND NOT EXISTS (SELECT 1 FROM settings WHERE key='cup_announcement:mpl-pre-season-cup-2026') AND name IN ('MPL Pre-Season Cup','Minglewood Pre-Season Cup','The Minglewood Cup')")
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('cup_announcement:mpl-pre-season-cup-2026',?)",(json.dumps({'source':'https://discord.com/channels/1448700292324655138/1450467148404363355/1558363241992822784','provided_by':'management','name':'The Minglewood Cup','event_start':'2026-10-13','event_end':'2026-10-15','format':'Single elimination','rounds_1_to_3':'2026-10-13, depending on number of confirmed clubs','semifinals_and_final':'2026-10-15','announced_start':'10:00 PM EST','bracket_draw':'2026-10-12','season_context':'Preseason ahead of Season 4','birmingham_participation':None}),))
        conn.execute('INSERT OR IGNORE INTO schema_migrations VALUES (3,?)',(utcnow(),))


def report_event(db,report_id):
    event=db.one('''SELECT c.*,rc.outcome,rc.outcome_evidence,rc.award_label,rc.award_scope
        FROM report_competitions rc JOIN competitions c USING(competition_key) WHERE report_id=?''',(report_id,))
    if event:
        announcement=db.setting('cup_announcement:'+event['competition_key'])
        if announcement:
            try:event['announcement']=json.loads(announcement)
            except (ValueError,TypeError):event['announcement']={'source':announcement}
    return event


def configure_report(db,report_id,key,outcome='Unknown',evidence=None,award_label='Cup Standout',award_scope=None):
    report=db.report(report_id)
    if not report or report['status'] in ('approved','skipped'):raise ValueError('Reopen this report before changing its competition.')
    competition=db.one('SELECT * FROM competitions WHERE competition_key=?',(key,))
    if not competition:raise ValueError('Select an existing competition.')
    if outcome not in ('Unknown','Advanced','Eliminated','Champions','Still competing'):
        raise ValueError('Use Unknown, Advanced, Eliminated, Champions or Still competing.')
    if outcome!='Unknown' and (not evidence or not competition['format']):
        raise ValueError('A confirmed outcome needs the event format and the supporting result or management confirmation. Otherwise choose Unknown.')
    if award_label not in ('Cup Standout','Player of the Tournament'):
        raise ValueError('Choose Cup Standout or Player of the Tournament.')
    if award_label=='Player of the Tournament' and not award_scope:
        raise ValueError('Confirm the award and its scope explicitly before using Player of the Tournament.')
    previous=report_event(db,report_id)
    with db.connect() as conn:
        conn.execute('''INSERT INTO report_competitions VALUES (?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET
            competition_key=excluded.competition_key,outcome=excluded.outcome,outcome_evidence=excluded.outcome_evidence,
            award_label=excluded.award_label,award_scope=excluded.award_scope''',
            (report_id,key,outcome,evidence,award_label,award_scope))
        if not previous or previous['competition_key']!=key:
            conn.execute("DELETE FROM report_matches WHERE report_id=?",(report_id,))
        conn.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL,include_development=? WHERE report_id=?",(int(competition['report_type']=='Practice'),report_id))
    return report_event(db,report_id)


def set_match_details(db,match_id,key,actor,evidence,**details):
    competition=db.one("SELECT * FROM competitions WHERE competition_key=? AND report_type='Cup'",(key,))
    if not competition or not evidence:raise ValueError('Cup details need an explicit competition and a source or management confirmation.')
    allowed={'stage','group_bracket','tie_key','leg','extra_time_for','extra_time_against','penalties_for','penalties_against'}
    if details.keys()-allowed:raise ValueError('Unknown cup detail.')
    for a,b in [('extra_time_for','extra_time_against'),('penalties_for','penalties_against')]:
        values=details.get(a),details.get(b)
        if any(v is not None for v in values) and any(type(v) is not int or v<0 for v in values):
            raise ValueError('Enter both non-negative scores, or leave both unknown.')
    if details.get('leg') not in (None,1,2):raise ValueError('Leg must be 1, 2 or unknown.')
    if details.get('leg') and not details.get('tie_key'):raise ValueError('A leg needs a tie identifier.')
    match=db.match(match_id)
    if not match:raise ValueError('Match not found.')
    if details.get('penalties_for') is not None and details['penalties_for']==details['penalties_against']:
        raise ValueError('A completed penalty shootout cannot finish level. Leave it unknown if incomplete.')
    if details.get('penalties_for') is not None and not details.get('tie_key') and match['birmingham_score']!=match['opponent_score']:
        raise ValueError('Shootout scores require a drawn final match score. Match scores include extra time, never shootout kicks.')
    if details.get('extra_time_for') is not None and (details['extra_time_for']!=match['birmingham_score'] or details['extra_time_against']!=match['opponent_score']):
        raise ValueError('Extra-time result must equal the final match score, excluding shootout kicks.')
    db.classify(match_id,'Cup',match['venue'],actor,competition['name'])
    fields=['match_id','competition_key','evidence']+sorted(allowed)
    values=[match_id,key,evidence]+[details.get(k) for k in sorted(allowed)]
    db.execute('INSERT INTO cup_match_details ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(match_id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in fields[1:]),values)


def snapshot(db,report_id):
    event=report_event(db,report_id)
    if not event:return None
    details=db.rows('''SELECT d.* FROM cup_match_details d JOIN report_matches rm USING(match_id)
        WHERE rm.report_id=? ORDER BY d.match_id''',(report_id,))
    return {'event':event,'match_details':details}


def verify_event(packet,fixtures):
    """Return source-backed event facts; compute aggregates only for complete ties."""
    from .report_verification import ReportHold
    context=packet.get('competition_context')
    if not context:return []
    event=context['event'];kind=event['report_type']
    expected={'Cup':'Cup','League':'Official','Practice':'Practice'}[kind]
    if any(f['match_type']!=expected for f in fixtures):
        raise ReportHold('This report contains a fixture from another report type. Change the selection before generating.')
    if kind!='Cup':return []
    by_id={f['match_id']:f for f in fixtures};details=context['match_details']
    if set(by_id)!={d['match_id'] for d in details} or any(d['competition_key']!=event['competition_key'] for d in details):
        raise ReportHold('Every selected cup fixture needs an explicit competition assignment. Unknown stages are fine.')
    facts=[('competition_name',event['name']),('event_dates',{'start':event['event_start'],'end':event['event_end']})]
    ties={}
    for d in details:
        f=by_id[d['match_id']]
        if not d['evidence']:raise ReportHold('Cup metadata is missing its source confirmation.')
        for field in ('stage','group_bracket','extra_time_for','extra_time_against','penalties_for','penalties_against'):
            if d.get(field) is not None:facts.append((f'match:{d["match_id"]}:{field}',d[field]))
        if d.get('tie_key'):ties.setdefault(d['tie_key'],[]).append((d,f))
    for key,legs in ties.items():
        if len(legs)>2 or len({d['leg'] for d,f in legs if d['leg']})!=sum(d['leg'] is not None for d,f in legs):
            raise ReportHold(f'Tie {key} has duplicate or unknown legs. Correct the leg numbers or leave the tie unknown.')
        if len(legs)==2 and {d['leg'] for d,f in legs}=={1,2}:
            if len({f['opponent'] for d,f in legs})!=1:raise ReportHold(f'Tie {key} has conflicting opponents.')
            if any(d.get('penalties_for') is not None for d,f in legs) and sum(f['birmingham_score']-f['opponent_score'] for d,f in legs)!=0:
                raise ReportHold(f'Tie {key} has a shootout but its aggregate is not level.')
            facts.append(('aggregate:'+key,{'for':sum(f['birmingham_score'] for d,f in legs),'against':sum(f['opponent_score'] for d,f in legs),'match_ids':[f['match_id'] for d,f in legs]}))
    if event['outcome']!='Unknown':
        if not event['format'] or not event['outcome_evidence']:
            raise ReportHold('Cup progression is unverified. Leave the outcome Unknown or confirm the format and result.')
        outcomes=[]
        for d in details:
            f=by_id[d['match_id']]
            delta=(d['penalties_for']-d['penalties_against']) if d.get('penalties_for') is not None else f['birmingham_score']-f['opponent_score']
            outcomes.append((d,delta))
        if event['outcome']=='Champions' and not any((d.get('stage') or '').strip().lower() in ('final','grand final') and delta>0 for d,delta in outcomes):
            raise ReportHold('A trophy claim needs a confirmed final victory among the supplied results.')
        if event['outcome']=='Eliminated' and not any(delta<0 for d,delta in outcomes):
            raise ReportHold('Elimination conflicts with the selected results; confirm the deciding fixture.')
        if event['outcome']=='Advanced' and not any(delta>0 for d,delta in outcomes):
            raise ReportHold('Advancement needs the deciding result and format; the selected results do not establish it.')
        if event['outcome']=='Still competing' and 'single elimination' in event['format'].lower() and any(delta<0 for d,delta in outcomes):
            raise ReportHold('Still competing conflicts with a selected single-elimination defeat.')
        facts.append(('confirmed_outcome',{'outcome':event['outcome'],'format':event['format'],'evidence':event['outcome_evidence']}))
    return facts
