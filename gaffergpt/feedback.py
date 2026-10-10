"""Measured player feedback, separate from Discord and any future AI provider."""
from .database import Database


def player_feedback(db, user_id):
    link=db.player_link(user_id)
    if not link:
        return 'Use /linkplayer first so Pep knows which stats belong to you.'
    name=link['player_name']
    rows=db.rows('''SELECT s.*,m.match_type,m.played_at,m.opponent FROM match_statistics s
    JOIN matches m USING(match_id) WHERE s.subject_type='player'
    AND m.match_type IN ('Official','Practice') ORDER BY m.played_at,m.match_id''')
    matching=[]
    for row in rows:
        try:
            if Database.player_name_key(row['subject_key'])[1]==link['name_key']:
                matching.append(row)
        except ValueError:
            continue
    rows=matching
    if not rows:
        return f'{name}: no player stats from classified matches yet. Pep needs a text recap with your stats and management must classify the match first.'
    lines=[f'PEP — PLAYER FEEDBACK: {name}', 'Based on saved stats; these suggest training priorities, not the cause of a performance.']
    for kind in ('Official','Practice'):
        grouped={}
        for row in rows:
            if row['match_type']==kind:
                grouped.setdefault(row['match_id'],{})[row['metric']]=row['value']
        if not grouped:
            continue
        recent=list(grouped.items())[-10:]
        lines.append(f'\n{kind.upper()}: {len(recent)} recent matches with stats')
        ratings=[v['rating'] for _,v in recent if 'rating' in v]
        if ratings:
            lines.append(f'Average rating: {sum(ratings)/len(ratings):.2f} ({len(ratings)} recorded ratings).')
        passes=[v for _,v in recent if 'passes_completed' in v and v.get('passes_attempted',0)>0]
        if passes:
            completed=sum(v['passes_completed'] for v in passes); attempted=sum(v['passes_attempted'] for v in passes)
            lines.append(f'Passing: {completed:g}/{attempted:g} completed ({100*completed/attempted:.1f}%).')
            lines.append('Training focus: practise receiving with an open body and choosing a clear passing lane; track whether completion improves.')
        tackles=[v for _,v in recent if 'tackles_won' in v and v.get('tackles_attempted',0)>0]
        if tackles:
            won=sum(v['tackles_won'] for v in tackles); attempted=sum(v['tackles_attempted'] for v in tackles)
            lines.append(f'Tackles: {won:g}/{attempted:g} won ({100*won/attempted:.1f}%).')
            lines.append('Training focus: jockey to close the lane, then tackle when the ball is exposed; compare tackle success next time.')
        for metric in ('goals','assists','shots','saves'):
            recorded=[v[metric] for _,v in recent if metric in v]
            if recorded:
                lines.append(f'{metric.capitalize()}: {sum(recorded):g} across {len(recorded)} matches with that metric recorded.')
    lines.append('\nUnknown and ignored matches are excluded. Missing stats are not treated as zero. Practice never changes the official record.')
    return '\n'.join(lines)
