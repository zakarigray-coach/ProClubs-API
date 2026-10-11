"""One shared, non-destructive SQLite store for Gaffer and Reporter."""
import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
 discord_user_id TEXT PRIMARY KEY NOT NULL, username TEXT NOT NULL,
 preferred_position TEXT NOT NULL, player_role TEXT NOT NULL, player_focus TEXT
);
CREATE TABLE IF NOT EXISTS player_links (
 discord_user_id TEXT PRIMARY KEY NOT NULL, username TEXT NOT NULL,
 player_name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
 linked_by TEXT NOT NULL, linked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS squad_tactics (
 tactic_id INTEGER PRIMARY KEY, tactic_name TEXT NOT NULL UNIQUE,
 formation TEXT NOT NULL, build_up_style TEXT NOT NULL,
 defensive_depth INTEGER NOT NULL CHECK(typeof(defensive_depth)='integer' AND defensive_depth BETWEEN 0 AND 100),
 custom_instructions TEXT
);
CREATE TABLE IF NOT EXISTS matches (
 match_id INTEGER PRIMARY KEY, source_message_id TEXT NOT NULL,
 source_channel_id TEXT NOT NULL, source_guild_id TEXT NOT NULL,
 source_part INTEGER NOT NULL DEFAULT 0, detected_at TEXT NOT NULL,
 played_at TEXT NOT NULL, date_source TEXT NOT NULL DEFAULT 'message',
 opponent TEXT, birmingham_score INTEGER CHECK(birmingham_score>=0),
 opponent_score INTEGER CHECK(opponent_score>=0), raw_recap TEXT NOT NULL,
 match_type TEXT NOT NULL DEFAULT 'Unknown' CHECK(match_type IN ('Unknown','Official','Practice','Ignored')),
 venue TEXT NOT NULL DEFAULT 'Unknown' CHECK(venue IN ('Unknown','Home','Away','Neutral')),
 competition TEXT, classification_status TEXT NOT NULL DEFAULT 'Unknown' CHECK(classification_status IN ('Unknown','Classified')),
 counts_official INTEGER NOT NULL DEFAULT 0 CHECK(counts_official IN (0,1)),
 report_eligible INTEGER NOT NULL DEFAULT 0 CHECK(report_eligible IN (0,1)),
 classified_by TEXT, classified_at TEXT, review_message_id TEXT,
 UNIQUE(source_guild_id,source_channel_id,source_message_id,source_part),
 CHECK((match_type='Unknown' AND classification_status='Unknown' AND counts_official=0 AND report_eligible=0)
 OR (match_type='Official' AND classification_status='Classified' AND counts_official=1 AND venue IN ('Home','Away','Neutral'))
 OR (match_type='Practice' AND classification_status='Classified' AND counts_official=0)
 OR (match_type='Ignored' AND classification_status='Classified' AND counts_official=0 AND report_eligible=0))
);
CREATE INDEX IF NOT EXISTS matches_by_date ON matches(played_at);
CREATE TABLE IF NOT EXISTS match_statistics (
 stat_id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
 subject_type TEXT NOT NULL CHECK(subject_type IN ('team','player')),
 subject_key TEXT NOT NULL, metric TEXT NOT NULL,
 value REAL NOT NULL, unit TEXT, source TEXT NOT NULL DEFAULT 'management',
 UNIQUE(match_id,subject_type,subject_key,metric)
);
CREATE TABLE IF NOT EXISTS classification_history (
 id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(match_id),
 actor_id TEXT NOT NULL, previous_type TEXT NOT NULL, new_type TEXT NOT NULL,
 venue TEXT NOT NULL, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_reports (
 report_id INTEGER PRIMARY KEY, week_start TEXT NOT NULL, week_end TEXT NOT NULL,
 owner_id TEXT NOT NULL, title TEXT, article TEXT, observations TEXT,
 include_development INTEGER NOT NULL DEFAULT 1 CHECK(include_development IN (0,1)),
 status TEXT NOT NULL DEFAULT 'selecting' CHECK(status IN ('selecting','confirmed','draft','approved','skipped')),
 created_at TEXT NOT NULL, confirmed_at TEXT, draft_sent_at TEXT,
 CHECK(week_end>week_start), UNIQUE(owner_id,week_start,week_end)
);
CREATE TABLE IF NOT EXISTS report_matches (
 report_id INTEGER NOT NULL REFERENCES weekly_reports(report_id) ON DELETE CASCADE,
 match_id INTEGER NOT NULL REFERENCES matches(match_id), PRIMARY KEY(report_id,match_id)
);
CREATE TABLE IF NOT EXISTS weekly_jobs (
 job_key TEXT PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES weekly_reports(report_id),
 due_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','sending','sent','skipped')),
 lease_until TEXT, sent_at TEXT, message_id TEXT, reminder_at TEXT, reminder_sent_at TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT
);
CREATE TABLE IF NOT EXISTS session_reviews (
 batch_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, sent_at TEXT, message_id TEXT
);
CREATE TABLE IF NOT EXISTS session_review_matches (
 batch_id INTEGER NOT NULL REFERENCES session_reviews(batch_id),
 match_id INTEGER NOT NULL UNIQUE REFERENCES matches(match_id), PRIMARY KEY(batch_id,match_id)
);
CREATE TABLE IF NOT EXISTS coaching_notes (
 note_id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
 user_id TEXT NOT NULL, created_at TEXT NOT NULL, supplied_analysis TEXT NOT NULL,
 formation TEXT NOT NULL DEFAULT '', advice TEXT NOT NULL, provider TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
"""


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (1,?)', (utcnow(),))
            db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (2,?)', (utcnow(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self, query, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(query, args)]

    def one(self, query, args=()):
        rows = self.rows(query, args)
        return rows[0] if rows else None

    def execute(self, query, args=()):
        with self.connect() as db:
            return db.execute(query, args).lastrowid

    def setting(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE key=?', (key,))
        return row['value'] if row else default

    def set_setting(self, key, value):
        self.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,str(value)))

    def register_player(self, user_id, username, position, role, focus=None):
        self.execute('''INSERT INTO players VALUES (?,?,?,?,?) ON CONFLICT(discord_user_id) DO UPDATE SET
        username=excluded.username, preferred_position=excluded.preferred_position,
        player_role=excluded.player_role, player_focus=excluded.player_focus''',
        (str(user_id),username,position,role,focus))

    @staticmethod
    def player_name_key(name):
        # Preserve display spelling; compare names without case/spacing differences.
        display=' '.join(unicodedata.normalize('NFKC', name).split())
        if not display or len(display)>80 or any(unicodedata.category(c).startswith('C') for c in display):
            raise ValueError('Use your exact player name, between 1 and 80 characters.')
        return display,display.casefold()

    def player_link(self, user_id):
        return self.one('SELECT * FROM player_links WHERE discord_user_id=?',(str(user_id),))

    def link_player(self, user_id, username, player_name, actor_id):
        display,key=self.player_name_key(player_name)
        try:
            self.execute('''INSERT INTO player_links VALUES (?,?,?,?,?,?)
            ON CONFLICT(discord_user_id) DO UPDATE SET username=excluded.username,
            player_name=excluded.player_name,name_key=excluded.name_key,
            linked_by=excluded.linked_by,linked_at=excluded.linked_at''',
            (str(user_id),username,display,key,str(actor_id),utcnow()))
        except sqlite3.IntegrityError as error:
            raise ValueError('That player name is already linked. Ask management to correct it.') from error
        return self.player_link(user_id)

    def unlink_player(self, user_id):
        self.execute('DELETE FROM player_links WHERE discord_user_id=?',(str(user_id),))

    def ingest(self, message_id, channel_id, guild_id, timestamp, text, parsed):
        # Dedupe by source message, never opponent/date/score.
        ids = []
        with self.connect() as db:
            for part, data in enumerate(parsed):
                cur = db.execute('''INSERT OR IGNORE INTO matches
                (source_message_id,source_channel_id,source_guild_id,source_part,detected_at,played_at,opponent,birmingham_score,opponent_score,raw_recap)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (str(message_id),str(channel_id),str(guild_id),part,utcnow(),timestamp,
                 data.get('opponent'),data.get('birmingham_score'),data.get('opponent_score'),text))
                if cur.rowcount:
                    ids.append(cur.lastrowid)
                    for stat in data.get('statistics',[]):
                        db.execute('''INSERT OR IGNORE INTO match_statistics
                        (match_id,subject_type,subject_key,metric,value,unit,source) VALUES (?,?,?,?,?,?,?)''',
                        (cur.lastrowid,stat['subject_type'],stat['subject_key'],stat['metric'],stat['value'],stat.get('unit'),stat['source']))
        return ids

    def match(self, match_id):
        return self.one('SELECT * FROM matches WHERE match_id=?', (match_id,))

    def ignore_setup_prompts(self, channel_id, guild_id, actor):
        from .parser import is_setup_prompt
        ignored=[]
        for row in self.rows("""SELECT * FROM matches WHERE match_type='Unknown'
                AND source_channel_id=? AND source_guild_id=? AND opponent IS NULL
                AND birmingham_score IS NULL AND opponent_score IS NULL""",
                (str(channel_id),str(guild_id))):
            if is_setup_prompt(row['raw_recap']):
                self.classify(row['match_id'],'Ignored','Unknown',actor)
                ignored.append(row['match_id'])
        return ignored

    def period_matches(self, start, end, eligible=False):
        query = 'SELECT * FROM matches WHERE played_at>=? AND played_at<?'
        if eligible:
            query += " AND report_eligible=1 AND match_type IN ('Official','Practice')"
        return self.rows(query+' ORDER BY played_at,match_id', (start,end))

    def classify(self, match_id, match_type, venue, actor, competition=None):
        if match_type not in ('Official','Practice','Ignored'):
            raise ValueError('Choose Official, Practice or Ignored.')
        if venue not in ('Home','Away','Neutral','Unknown') or (match_type=='Official' and venue=='Unknown'):
            raise ValueError('Official matches need a venue.')
        with self.connect() as db:
            row = db.execute('SELECT * FROM matches WHERE match_id=?',(match_id,)).fetchone()
            if row is None:
                raise ValueError('Match not found.')
            db.execute('''UPDATE matches SET match_type=?,venue=?,competition=?,classification_status='Classified',
            counts_official=?,report_eligible=?,classified_by=?,classified_at=? WHERE match_id=?''',
            (match_type,venue,competition,int(match_type=='Official'),int(match_type!='Ignored'),str(actor),utcnow(),match_id))
            db.execute('INSERT INTO classification_history(match_id,actor_id,previous_type,new_type,venue,changed_at) VALUES (?,?,?,?,?,?)',
            (match_id,str(actor),row['match_type'],match_type,venue,utcnow()))
            # A correction invalidates affected drafts so stale facts cannot be approved.
            db.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL,confirmed_at=NULL WHERE report_id IN (SELECT report_id FROM report_matches WHERE match_id=?)",(match_id,))
            if match_type=='Ignored':
                db.execute('DELETE FROM report_matches WHERE match_id=?',(match_id,))

    def report(self, report_id):
        return self.one('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,))

    def open_report(self, start, end, owner):
        self.execute('INSERT OR IGNORE INTO weekly_reports(week_start,week_end,owner_id,created_at) VALUES (?,?,?,?)', (start,end,str(owner),utcnow()))
        return self.one('SELECT * FROM weekly_reports WHERE owner_id=? AND week_start=? AND week_end=?',(str(owner),start,end))

    def selected(self, report_id):
        return self.rows('SELECT m.* FROM report_matches r JOIN matches m USING(match_id) WHERE report_id=? ORDER BY played_at,match_id',(report_id,))

    def replace_page_selection(self, report_id, page_ids, selected_ids):
        if not set(selected_ids)<=set(page_ids):
            raise ValueError('Selection contains a match outside this page.')
        with self.connect() as db:
            report = db.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
            if not report or report['status'] not in ('selecting','draft','confirmed'):
                raise ValueError('This report is closed.')
            for mid in selected_ids:
                row=db.execute('SELECT * FROM matches WHERE match_id=?',(mid,)).fetchone()
                if not row or not row['report_eligible'] or not (report['week_start']<=row['played_at']<report['week_end']):
                    raise ValueError('Match is no longer eligible.')
            for mid in page_ids:
                db.execute('DELETE FROM report_matches WHERE report_id=? AND match_id=?',(report_id,mid))
            for mid in selected_ids:
                db.execute('INSERT INTO report_matches VALUES (?,?)',(report_id,mid))
            db.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL,confirmed_at=NULL WHERE report_id=?",(report_id,))

    def confirm_report(self, report_id, acknowledge_unknown=False):
        with self.connect() as db:
            r=db.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
            if not r or r['status'] not in ('selecting','draft','confirmed'):
                raise ValueError('This report is closed.')
            unknown=db.execute("SELECT COUNT(*) FROM matches WHERE played_at>=? AND played_at<? AND match_type='Unknown'",(r['week_start'],r['week_end'])).fetchone()[0]
            if unknown and not acknowledge_unknown:
                raise ValueError(f'{unknown} matches still need classification. Review them first.')
            selected=db.execute('SELECT m.* FROM report_matches rm JOIN matches m USING(match_id) WHERE report_id=?',(report_id,)).fetchall()
            if not selected:
                raise ValueError('Choose at least one match first.')
            if any(not m['report_eligible'] or m['match_type'] not in ('Official','Practice') for m in selected):
                raise ValueError('A selected match needs review.')
            db.execute("UPDATE weekly_reports SET status='confirmed',confirmed_at=? WHERE report_id=?",(utcnow(),report_id))

    def official_record(self):
        rows=self.rows("SELECT * FROM matches WHERE counts_official=1 AND birmingham_score IS NOT NULL AND opponent_score IS NOT NULL")
        return {'played':len(rows),'wins':sum(m['birmingham_score']>m['opponent_score'] for m in rows),
                'draws':sum(m['birmingham_score']==m['opponent_score'] for m in rows),
                'losses':sum(m['birmingham_score']<m['opponent_score'] for m in rows)}
