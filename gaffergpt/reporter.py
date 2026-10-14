"""Reporter reads the shared store and prepares drafts; it never publishes."""
import json
import secrets
import sqlite3
from datetime import datetime,timezone,timedelta
from .database import utcnow
from .article_writer import period_label
from . import report_audit
from .report_verification import source_identity
from .analysis import FactualGaffer
from .weekly_intake import CONTENT_SCHEMA
from .excel_stats import player_totals, stats_text
from .editorial import choose_editorial, editorial_lead, editorial_headline


def match_label(m):
    opponent=(m['opponent'] or 'Opponent not yet identified')[:80]
    own='?' if m['birmingham_score'] is None else m['birmingham_score']
    other='?' if m['opponent_score'] is None else m['opponent_score']
    if m['venue']=='Away' and m['match_type']=='Official':
        return f'{opponent} {other}–{own} Birmingham City — Away'
    suffix='Practice' if m['match_type']=='Practice' else 'Cup' if m['match_type']=='Cup' else m['venue']
    return f'Birmingham City {own}–{other} {opponent} — {suffix}'


class Reporter:
    def __init__(self, db, analyst=None, writer=None):
        self.db=db
        self.analyst=analyst or FactualGaffer()
        self.writer=writer

    def generate(self, report_id):
        if not self.writer:return self._generate(report_id)
        lease=secrets.token_hex(16)
        with self.db.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS report_generation_leases(report_id INTEGER PRIMARY KEY REFERENCES weekly_reports(report_id),owner TEXT NOT NULL,expires_at TEXT NOT NULL)')
            conn.execute('DELETE FROM report_generation_leases WHERE expires_at<=?',(utcnow(),))
            try:conn.execute('INSERT INTO report_generation_leases VALUES(?,?,?)',(report_id,lease,(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()))
            except sqlite3.IntegrityError:
                raise ValueError('This article is already being prepared. Wait for its private draft; do not generate another copy.') from None
        try:
            cached=self._cached(report_id)
            if cached:return cached
            if hasattr(self.writer,'reset_audit'):self.writer.reset_audit()
            audit_id=report_audit.start(self.db,report_id)
            try:
                article=self._generate(report_id)
                report_audit.finish(self.db,audit_id,self.writer,
                    'passed' if getattr(self.writer,'last_verification',None) else 'unverified_legacy_writer')
                return article
            except Exception as error:
                report_audit.finish(self.db,audit_id,self.writer,'held',error)
                raise
        finally:self.db.execute('DELETE FROM report_generation_leases WHERE report_id=? AND owner=?',(report_id,lease))

    def _cached(self,report_id):
        from .article_writer import WRITING_VERSION
        from .report_verification import digest
        report=self.db.report(report_id)
        if not report or report['status']!='confirmed' or not report['article']:return None
        exists=self.db.one("SELECT 1 FROM sqlite_master WHERE name='report_generation_audit'")
        if not exists:return None
        audit=self.db.one("SELECT * FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
        if not audit:return None
        proof=json.loads(audit['verification'] or '{}')
        if proof.get('writing_version')!=WRITING_VERSION or proof.get('model')!=getattr(self.writer,'model',None):return None
        checked={'title':report['title'],'body':report['article'].split('\n\n',1)[1].strip()}
        if digest(checked)!=audit['article_hash']:return None
        with self.db.connect() as conn:
            conn.execute(CONTENT_SCHEMA)
            management=conn.execute('SELECT notes,player_name,player_evidence FROM weekly_report_content WHERE report_id=?',(report_id,)).fetchone()
        if proof.get('management_hash')!=digest(dict(management) if management else None):return None
        try:report_audit.assert_current(self.db,report_id,json.loads(audit['fact_sheet']))
        except ValueError:return None
        self.db.execute("UPDATE weekly_reports SET status='draft' WHERE report_id=? AND status='confirmed'",(report_id,))
        return report['article']

    def _generate(self, report_id):
        # One transaction prevents classification changes racing draft creation.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            report=dict(conn.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone())
            if report['status']!='confirmed':
                raise ValueError('Confirm your match selections before generating.')
            matches=[dict(r) for r in conn.execute('SELECT m.* FROM report_matches rm JOIN matches m USING(match_id) WHERE report_id=? ORDER BY played_at,match_id',(report_id,))]
            if not matches or any(not m['report_eligible'] for m in matches):
                raise ValueError('Selected matches are not eligible.')
            statistics=[]
            for m in matches:
                statistics.extend(dict(r) for r in conn.execute('SELECT * FROM match_statistics WHERE match_id=?',(m['match_id'],)))
            analysis_matches=matches if report['include_development'] else [m for m in matches if m['match_type'] in ('Official','Cup')]
            observations=self.analyst.analyze(analysis_matches,statistics)
            official=[m for m in matches if m['match_type']=='Official']
            practices=[m for m in matches if m['match_type']=='Practice']
            summary=observations['summaries']['Official']
            if summary['scored_matches']:
                wins_word='win' if summary['wins']==1 else 'wins'
                matches_word='match' if summary['scored_matches']==1 else 'matches'
                title=f"Birmingham City record {summary['wins']} {wins_word} from {summary['scored_matches']} selected official {matches_word}"
            elif practices and report['include_development']:
                title='Birmingham City: a week on the training ground'
            else:
                title='Birmingham City: the selected match week'
            editorial=choose_editorial(conn,report_id)
            # Include the reporting period so recurring result patterns have distinct headlines.
            factual_subheadline=title
            title=editorial_headline(editorial,report['week_start'])
            lines=['RT FOOTBALL MEDIA',title,factual_subheadline,f"By {editorial['reporter']} | RT Football Media",'DRAFT — awaiting Coach review',
                   f"Reporting period: {report['week_start']} to {report['week_end']} (end exclusive).",
                   'Coverage is limited to the matches selected by management.','',editorial_lead(editorial,summary),'']
            if official:
                lines+=['COMPETITIVE RECAP']
                for m in official:
                    lines.append(f"Match #{m['match_id']}: {match_label(m)}.")
                    if m['birmingham_score'] is not None and m['opponent_score'] is not None:
                        result='a win' if m['birmingham_score']>m['opponent_score'] else 'a draw' if m['birmingham_score']==m['opponent_score'] else 'a defeat'
                        lines.append(f"Birmingham recorded {result} in this {m['venue'].lower()} fixture"+(f" in {m['competition']}." if m['competition'] else '.'))
                if summary['scored_matches']:
                    lines+=['','WEEK BY THE NUMBERS',
                        f"The {summary['scored_matches']} selected official matches with known scores produced {summary['wins']} wins, {summary['draws']} draws and {summary['losses']} defeats. Birmingham scored {summary['goals_for']} goals and conceded {summary['goals_against']}."]
                if summary['selected']>summary['scored_matches']:
                    lines.append('Fixtures with incomplete scores are excluded from the result totals.')
            if observations['doubleheaders']:
                lines+=['','TWO GAMES, TWO RESULTS']
                by_id={m['match_id']:m for m in official}
                for night in observations['doubleheaders']:
                    lines.append(f"The selected home-and-away meeting with {night['opponent']} on {night['date']} contains two separate official fixtures:")
                    lines.extend(match_label(by_id[mid])+f" (match #{mid})." for mid in night['match_ids'])
            lines+=['','GAFFER’S CORNER']
            trends=observations['trends']
            if trends:
                for t in trends:
                    sequence=' → '.join(f'{v:g}' for v in t['values'])
                    lines.append(f"Against {t['opponent']}, {t['subject']}'s {t['metric'].replace('_',' ')} was {sequence} {t['unit'] or ''} across {len(t['match_ids'])} selected {t['match_type'].lower()} samples: an observed {t['direction']} pattern.")
                lines.append('The pattern is a starting point for coaching review, not proof of a tactical cause or lasting improvement.')
            else:
                lines.append('The selected data does not yet provide three comparable samples for a trend. More recorded performances are needed before judging sustained development.')
            if report['include_development'] and practices:
                lines+=['','FROM THE TRAINING GROUND',
                    'Practice results are retained for development and remain separate from Birmingham’s official record.']
                lines.extend(f"Match #{m['match_id']}: {match_label(m)}." for m in practices)
            comparisons=observations['comparisons']
            if comparisons:
                lines+=['','DEVELOPMENT WATCH' if report['include_development'] and practices else 'PERFORMANCE COMPARISON']
                for c in comparisons:
                    lines.append(f"{c['subject']} — {c['metric'].replace('_',' ')}: {c['before']:g} to {c['after']:g} {c['unit'] or ''} between selected {c['from_type'].lower()} match #{c['from_match']} and {c['to_type'].lower()} match #{c['to_match']}.".strip())
                lines.append('Missing metrics are not treated as zero. Match conditions, minutes played and positions can affect these comparisons.')
            player_sections={}
            for kind in ('Official','Cup','Practice'):
                if kind=='Practice' and not report['include_development']:continue
                ids={m['match_id'] for m in matches if m['match_type']==kind}
                players=player_totals([s for s in statistics if s['match_id'] in ids and s.get('source')=='PCT+ Excel'])
                if players:
                    player_sections[kind]=players
                    lines+=['',('OFFICIAL PLAYER PERFORMANCES' if kind=='Official' else 'PRACTICE PLAYER PERFORMANCES'),stats_text(players)]
            observations['player_statistics']=player_sections
            conn.execute(CONTENT_SCHEMA)
            supplied=conn.execute('SELECT * FROM weekly_report_content WHERE report_id=?',(report_id,)).fetchone()
            if supplied and supplied['notes']:
                lines+=['','FROM THE CLUB DESK','Management-supplied observations (not independently verified):',supplied['notes']]
            if supplied and supplied['player_name'] and supplied['player_evidence']:
                lines+=['','PLAYER OF THE WEEK',supplied['player_name']+' — '+supplied['player_evidence'], 'Selected by management. No interview was requested.']
            lines+=['','EDITORIAL NOTE','Scores and statistics come from the selected database records. No quotes, injuries, events or future fixtures have been invented. This draft has not been published.']
            article='\n'.join(lines)
            if self.writer:
                recent=[{'title':r['title'],'lead':(r['article'] or '')[:900]} for r in conn.execute(
                    "SELECT title,article FROM weekly_reports WHERE report_id<>? AND article IS NOT NULL ORDER BY report_id DESC LIMIT 6",(report_id,))]
                packet={'period':period_label(report),'reporter':editorial['reporter'],'style':editorial['style'],
                        'matches':[{k:m.get(k) for k in ('played_at','opponent','birmingham_score','opponent_score','match_type','venue','competition')} for m in matches
                                   if m['match_type'] in ('Official','Cup') or report['include_development']],
                        'observations':observations,'management':{k:supplied[k] for k in ('notes','player_name','player_evidence')} if supplied else None,'recent_articles':recent}
                included=[m for m in matches if m['match_type'] in ('Official','Cup') or report['include_development']]
                included_ids={m['match_id'] for m in included}
                from .competitions import snapshot
                packet['competition_context']=snapshot(self.db,report_id)
                packet['source_matches']=included
                packet['statistics']=[s for s in statistics if s['match_id'] in included_ids]
                packet['excluded_names']=[r['opponent'] for r in conn.execute(
                    'SELECT DISTINCT opponent FROM matches WHERE match_id NOT IN ('+','.join('?' for _ in matches)+') AND opponent IS NOT NULL',
                    [m['match_id'] for m in matches]) if r['opponent'] not in {m['opponent'] for m in included}]
                known_players={s['subject_key'] for s in packet['statistics'] if s['subject_type']=='player'}
                packet['excluded_names'] += [r['subject_key'] for r in conn.execute("SELECT DISTINCT subject_key FROM match_statistics WHERE subject_type='player'") if r['subject_key'] not in known_players]
                held=conn.execute("SELECT source_hash,fact_sheet,attempts FROM report_generation_audit WHERE report_id=? AND state='held' ORDER BY audit_id DESC LIMIT 1",(report_id,)).fetchone()
                if held:
                    previous=json.loads(held['attempts'])
                    drafts=[a for a in previous if isinstance(a.get('article'),dict)]
                    if drafts:
                        packet['recovery']={'source_hash':held['source_hash'],'source_identity':source_identity(json.loads(held['fact_sheet'])),'article':drafts[-1]['article'],'error':'\n'.join(a['error'] for a in drafts if a.get('error')) or 'Complete all current checks.'}
                # Release the write lock while the remote sports desk works.
                conn.commit()
                title,body=self.writer.write(packet)
                conn.execute('BEGIN IMMEDIATE')
                current=conn.execute('SELECT * FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
                current_matches=[dict(r) for r in conn.execute('SELECT m.* FROM report_matches rm JOIN matches m USING(match_id) WHERE report_id=? ORDER BY played_at,match_id',(report_id,))]
                current_stats=[]
                for m in current_matches:
                    current_stats.extend(dict(r) for r in conn.execute('SELECT * FROM match_statistics WHERE match_id=?',(m['match_id'],)))
                current_content=conn.execute('SELECT notes,player_name,player_evidence FROM weekly_report_content WHERE report_id=?',(report_id,)).fetchone()
                old_content={k:supplied[k] for k in ('notes','player_name','player_evidence')} if supplied else None
                if (dict(current_content) if current_content else None)!=old_content:
                    raise ValueError('Management notes or award selection changed during writing; report held for fresh verification.')
                if current['status']!='confirmed' or current_matches!=matches or current_stats!=statistics or current['include_development']!=report['include_development'] or snapshot(self.db,report_id)!=packet.get('competition_context'):
                    raise ValueError('Report facts changed during writing; regenerate using the latest selections.')
                article='\n'.join(['RT FOOTBALL MEDIA',title,f"By {editorial['reporter']} | RT Football Media",
                                   period_label(report),'DRAFT — awaiting Coach review','',body])
            observations['editorial']={key:editorial[key] for key in ('reporter','opening','style')}
            conn.execute("UPDATE weekly_reports SET title=?,article=?,observations=?,status='draft' WHERE report_id=?",(title,article,json.dumps(observations),report_id))
        return article
