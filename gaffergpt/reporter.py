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
            analysis_matches=matches if report['include_development'] else [m for m in matches if m['match_type']=='Official']
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
            lines=['RT FOOTBALL MEDIA',title,'DRAFT — awaiting Coach review',
                   f"Reporting period: {report['week_start']} to {report['week_end']} (end exclusive).",
                   'Coverage is limited to the matches selected by management.','']
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
            lines+=['','EDITORIAL NOTE','Scores and statistics come from the selected database records. No quotes, injuries, events or future fixtures have been invented. This draft has not been published.']
            article='\n'.join(lines)
            conn.execute("UPDATE weekly_reports SET title=?,article=?,observations=?,status='draft' WHERE report_id=?",(title,article,json.dumps(observations),report_id))
        return article
