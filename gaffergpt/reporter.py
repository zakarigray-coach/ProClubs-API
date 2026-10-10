"""Reporter reads the shared store and prepares drafts; it never publishes."""
import json
from .analysis import FactualGaffer


def match_label(m):
    opponent=(m['opponent'] or 'Opponent not yet identified')[:80]
    own='?' if m['birmingham_score'] is None else m['birmingham_score']
    other='?' if m['opponent_score'] is None else m['opponent_score']
    if m['venue']=='Away' and m['match_type']=='Official':
        return f'{opponent} {other}–{own} Birmingham City — Away'
    suffix='Practice' if m['match_type']=='Practice' else m['venue']
    return f'Birmingham City {own}–{other} {opponent} — {suffix}'


class Reporter:
    def __init__(self, db, analyst=None):
        self.db=db
        self.analyst=analyst or FactualGaffer()

    def generate(self, report_id):
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
            observations=self.analyst.analyze(matches,statistics)
            official=[m for m in matches if m['match_type']=='Official']
            practices=[m for m in matches if m['match_type']=='Practice']
            title='Birmingham City: the selected match week'
            lines=['RT FOOTBALL MEDIA',title,'DRAFT — awaiting Coach review','']
            if official:
                lines+=['COMPETITIVE RECAP']
                lines.extend(f"Match #{m['match_id']}: {match_label(m)}." for m in official)
                complete=[m for m in official if m['birmingham_score'] is not None and m['opponent_score'] is not None]
                if complete:
                    lines+=['','WEEK BY THE NUMBERS',f"Selected official matches with verified scores: {len(complete)}. Goals scored: {sum(m['birmingham_score'] for m in complete)}. Goals conceded: {sum(m['opponent_score'] for m in complete)}."]
            lines+=['','GAFFER’S CORNER','These observations cover only the matches Coach selected. Missing statistics have been left out.']
            if report['include_development'] and practices:
                lines+=['','FROM THE TRAINING GROUND']
                lines.extend(f"Match #{m['match_id']}: {match_label(m)}. This practice does not count toward the official record." for m in practices)
            comparisons=observations['comparisons']
            if not report['include_development']:
                comparisons=[c for c in comparisons if c['from_type']=='Official' and c['to_type']=='Official']
            if comparisons:
                lines+=['','DEVELOPMENT WATCH' if report['include_development'] else 'PERFORMANCE COMPARISON']
                for c in comparisons:
                    lines.append(f"{c['subject']} — {c['metric']}: {c['before']:g} to {c['after']:g} {c['unit'] or ''} between selected matches #{c['from_match']} and #{c['to_match']}.".strip())
                lines.append('These are measured changes; they do not establish a tactical cause or prove lasting improvement.')
            article='\n'.join(lines)
            conn.execute("UPDATE weekly_reports SET title=?,article=?,observations=?,status='draft' WHERE report_id=?",(title,article,json.dumps(observations),report_id))
        return article
