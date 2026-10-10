"""Measured comparisons and trends, independent of Discord and AI providers."""
from collections import defaultdict
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class AnalysisProvider(Protocol):
    def analyze(self, matches: list[dict], statistics: list[dict]) -> dict: ...


LOWER_BETTER={'goals_conceded','shots_conceded','possession_lost'}
HIGHER_BETTER={'shots','chances_created','pass_accuracy','passing','possession','rating',
               'pass_completion','tackle_success','finishing'}


def direction(metric, values):
    deltas=[b-a for a,b in zip(values,values[1:])]
    if all(d==0 for d in deltas):
        return 'steady'
    rising=all(d>=0 for d in deltas)
    falling=all(d<=0 for d in deltas)
    if not rising and not falling:
        return 'mixed'
    if metric not in LOWER_BETTER|HIGHER_BETTER:
        return 'increasing' if rising else 'decreasing'
    return 'improving' if (rising and metric in HIGHER_BETTER) or (falling and metric in LOWER_BETTER) else 'declining'


class FactualGaffer:
    def analyze(self, matches, statistics):
        # Unknown/ignored records and unselected statistics cannot enter an analysis.
        matches=[m for m in matches if m['match_type'] in ('Official','Practice')]
        ids={m['match_id'] for m in matches}
        metrics={}
        for stat in statistics:
            if stat['match_id'] not in ids:
                continue
            key=(stat['subject_type'], ' '.join(stat['subject_key'].split()).casefold(),stat['metric'])
            metrics.setdefault(stat['match_id'],{})[key]=dict(stat)
        for m in matches:
            bucket=metrics.setdefault(m['match_id'],{})
            if m.get('birmingham_score') is not None and m.get('opponent_score') is not None:
                for metric,value in [('goals_scored',m['birmingham_score']),('goals_conceded',m['opponent_score'])]:
                    bucket[('team','birmingham city',metric)]={'subject_key':'Birmingham City','value':value,'unit':'count'}
            subjects={(a,b) for a,b,c in bucket}
            for subject in subjects:
                for label,numerator,denominator in [('pass_completion','passes_completed','passes_attempted'),('tackle_success','tackles_won','tackles_attempted'),('finishing','goals','shots')]:
                    n=bucket.get((*subject,numerator)); d=bucket.get((*subject,denominator))
                    if n and d and d['value']>0 and 0<=n['value']<=d['value']:
                        bucket[(*subject,label)]={'subject_key':n['subject_key'],'value':100*n['value']/d['value'],'unit':'%'}
        ordered=sorted(matches,key=lambda m:(m['played_at'],m['match_id']))
        opponents=defaultdict(list)
        for m in ordered:
            if m.get('opponent'):
                opponents[' '.join(m['opponent'].split()).casefold()].append(m)
        comparisons=[]; trends=[]; doubleheaders=[]
        for meetings in opponents.values():
            for previous,current in zip(meetings,meetings[1:]):
                before=metrics[previous['match_id']]; after=metrics[current['match_id']]
                for key in sorted(before.keys() & after.keys()):
                    if before[key]['unit']!=after[key]['unit']:
                        continue
                    comparisons.append({'from_match':previous['match_id'],'to_match':current['match_id'],
                        'subject_type':key[0],'subject':after[key]['subject_key'],'metric':key[2],
                        'before':before[key]['value'],'after':after[key]['value'],'unit':after[key]['unit'],
                        'from_type':previous['match_type'],'to_type':current['match_type']})
            # Keep practice and official trend samples distinct.
            for kind in ('Official','Practice'):
                samples=defaultdict(list)
                for m in meetings:
                    if m['match_type']==kind:
                        for key,stat in metrics[m['match_id']].items():
                            samples[(*key,stat['unit'])].append((m['match_id'],stat))
                for key,series in sorted(samples.items(),key=lambda x:str(x[0])):
                    if len(series)<3:
                        continue
                    values=[s['value'] for _,s in series]
                    trends.append({'opponent':meetings[0]['opponent'],'match_type':kind,
                        'subject_type':key[0],'subject':series[-1][1]['subject_key'],'metric':key[2],
                        'unit':key[3],'match_ids':[mid for mid,_ in series],'values':values,
                        'direction':direction(key[2],values)})
            nights=defaultdict(list)
            for m in meetings:
                if m['match_type']=='Official':
                    # Detect a two-game night only with matching competition and Eastern date.
                    date=datetime.fromisoformat(m['played_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                    nights[(date,m.get('competition'))].append(m)
            for (date,competition),night in nights.items():
                if len(night)==2 and {m['venue'] for m in night}=={'Home','Away'}:
                    doubleheaders.append({'opponent':night[0]['opponent'],'date':date,
                        'competition':competition,'match_ids':[m['match_id'] for m in night]})
        summaries={}
        for kind in ('Official','Practice'):
            group=[m for m in matches if m['match_type']==kind]
            complete=[m for m in group if m.get('birmingham_score') is not None and m.get('opponent_score') is not None]
            summaries[kind]={'selected':len(group),'scored_matches':len(complete),
                'wins':sum(m['birmingham_score']>m['opponent_score'] for m in complete),
                'draws':sum(m['birmingham_score']==m['opponent_score'] for m in complete),
                'losses':sum(m['birmingham_score']<m['opponent_score'] for m in complete),
                'goals_for':sum(m['birmingham_score'] for m in complete),
                'goals_against':sum(m['opponent_score'] for m in complete)}
        return {'official_ids':[m['match_id'] for m in matches if m['match_type']=='Official'],
                'practice_ids':[m['match_id'] for m in matches if m['match_type']=='Practice'],
                'comparisons':comparisons,'trends':trends,'doubleheaders':doubleheaders,'summaries':summaries}


def tracking_text(observations):
    lines=['PEP — DEVELOPMENT TRACKING']
    for kind,summary in observations['summaries'].items():
        lines.append(f"{kind}: {summary['selected']} classified matches; {summary['scored_matches']} with known scores.")
    for t in observations['trends']:
        sequence=' → '.join(f'{v:g}' for v in t['values'])
        lines.append(f"{t['match_type']} vs {t['opponent']}: {t['subject']} / {t['metric']} {sequence} {t['unit'] or ''} — {t['direction']} across {len(t['match_ids'])} recorded samples (matches {', '.join('#'+str(i) for i in t['match_ids'])}).")
    if not observations['trends']:
        lines.append('No three-match trend yet. At least three recorded samples against the same opponent in the same match category are needed.')
    for c in observations['comparisons']:
        if c['from_type']=='Practice' and c['to_type']=='Official':
            lines.append(f"Practice to official: {c['subject']} / {c['metric']} {c['before']:g} to {c['after']:g} {c['unit'] or ''} (#{c['from_match']} → #{c['to_match']}).")
    lines.append('Changes describe recorded metrics, not proof of their tactical cause. Different positions, minutes and opponents affect comparisons. Missing values stay missing.')
    return '\n'.join(lines)
