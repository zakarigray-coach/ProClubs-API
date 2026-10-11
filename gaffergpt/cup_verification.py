"""Cup claims use event evidence, never ordinary fixture-score references."""
import re


def cover_event_claim(fact,quote,start,candidates,sheet):
    metric,value=fact['metric'],fact['value'];covered=set()
    if metric=='competition_name':
        if value not in quote:raise ValueError('Preserve the exact competition name.')
        return covered
    if metric=='confirmed_outcome':
        if value['outcome'].lower() not in quote.lower():
            raise ValueError('Cup outcome must match its explicit confirmation.')
        return covered
    if metric=='event_dates':
        from datetime import date
        dates=[date.fromisoformat(d) for d in value.values() if d]
        allowed={n for d in dates for n in (d.day,d.year)}
        for a,b,n in candidates:
            if n in allowed:covered.add((a,b))
        return covered
    if metric.startswith('aggregate:'):
        if not re.search(r'\baggregate\b',quote,re.I):raise ValueError('Aggregate scores need an explicit aggregate label.')
        values=value['for'],value['against']
    elif ':penalties_' in metric:
        if not re.search(r'\bpenalt(?:y|ies)|shootout\b',quote,re.I):raise ValueError('Shootout figures need a penalty label.')
        _,mid,field=metric.split(':')
        d=next(d for d in sheet['competition_context']['match_details'] if d['match_id']==int(mid))
        values=d['penalties_for'],d['penalties_against']
        opponent=next(f['opponent'] for f in sheet['fixtures'] if f['match_id']==int(mid))
        if opponent not in quote:raise ValueError('Name the shootout opponent.')
    elif ':extra_time_' in metric:
        if not re.search(r'extra[- ]time',quote,re.I):raise ValueError('Extra-time scores need an explicit extra-time label.')
        _,mid,field=metric.split(':')
        d=next(d for d in sheet['competition_context']['match_details'] if d['match_id']==int(mid))
        values=d['extra_time_for'],d['extra_time_against']
    else:
        if str(value) not in quote:raise ValueError('Stage/group must match supplied metadata exactly.')
        return {(a,b) for a,b,n in candidates if str(n) in str(value).split()}
    for m in re.finditer(r'\b(\d+)\s*[-–]\s*(\d+)\b',quote):
        if tuple(map(int,m.groups()))==values:
            covered.update({(start+m.start(1),start+m.end(1)),(start+m.start(2),start+m.end(2))})
    if not covered:raise ValueError('Cup aggregate/shootout score differs from its source.')
    return covered
