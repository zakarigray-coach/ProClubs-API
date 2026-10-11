"""Calculate reporting figures in Python and bind them to named factual sentences."""
import re
from collections import Counter

def fact_registry(packet):
    facts={}
    for kind in ('Official','Practice'):
        rows=[m for m in packet['matches'] if m['match_type']==kind]
        if not rows:continue
        scored=[m for m in rows if m['birmingham_score'] is not None and m['opponent_score'] is not None]
        wins=sum(m['birmingham_score']>m['opponent_score'] for m in scored)
        draws=sum(m['birmingham_score']==m['opponent_score'] for m in scored)
        losses=len(scored)-wins-draws
        gf=sum(m['birmingham_score'] for m in scored);ga=sum(m['opponent_score'] for m in scored)
        facts[kind+'_record']=f'Birmingham City recorded {wins} {'win' if wins==1 else 'wins'}, {draws} {'draw' if draws==1 else 'draws'} and {losses} {'defeat' if losses==1 else 'defeats'} across {len(scored)} {kind.lower()} matches, scoring {gf} goals and conceding {ga}.'
        for i,m in enumerate(scored):
            facts[f'{kind}_match_{i}']=f"Birmingham City {'beat' if m['birmingham_score']>m['opponent_score'] else 'drew with' if m['birmingham_score']==m['opponent_score'] else 'lost to'} {m['opponent']} {m['birmingham_score']}–{m['opponent_score']} in {kind.lower()}."
        for i,p in enumerate(packet.get('observations',{}).get('player_statistics',{}).get(kind,[])):
            groups={'attack':[('goals','goals'),('assists','assists'),('shots','shots'),('shots_on_target','shots on target')],
                    'defence':[('tackles_won','tackles won'),('interceptions','interceptions'),('saves','saves')],
                    'dribbles':[('dribbles_completed','completed dribbles')]}
            for group,metrics in groups.items():
                parts=[f'{p[key]:g} {label}' for key,label in metrics if key in p and p[key]!=0]
                if parts:facts[f'{kind}_player_{i}_{group}']=f"{p['player']} recorded "+', '.join(parts)+f" across {p['appearances']} {kind.lower()} appearances."
            if 'average_rating' in p:facts[f'{kind}_player_{i}_rating']=f"{p['player']} averaged a {p['average_rating']:.2f} rating across {p['appearances']} {kind.lower()} appearances."
            if p.get('pass_accuracy') is not None:facts[f'{kind}_player_{i}_passing']=f"{p['player']} completed {p['passes_completed']:g} of {p['passes_attempted']:g} passes ({p['pass_accuracy']:.1f}%) in the selected {kind.lower()} matches."

    management=packet.get('management') or {}
    if management.get('player_name'):
        facts['award']=f"{management['player_name']} is management’s confirmed Player of the Week."
    return facts

TOKEN=re.compile(r'\[\[([A-Za-z0-9_]+)\]\]')
NUMBER_WORDS=re.compile(r'\b(?:zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|hundred)\b',re.I)

def render_checked(result,facts,packet):
    title=result.get('title','').strip();body=result.get('body','').strip()
    body=re.sub(r'\b[Tt]wo (other|additional) fixtures\b',lambda m:m[1].capitalize()+' fixtures',body)
    body=re.sub(r'\bThose two summary phrases\b','Those results',body,flags=re.I)
    if not title or len(body.split())<20:raise ValueError('Incomplete article')
    used=TOKEN.findall(body)
    if not used or any(k not in facts for k in used):raise ValueError('Unknown or missing fact references')
    if any(n>1 for n in Counter(used).values()):raise ValueError('Repeated statistical paragraph')
    raw=TOKEN.sub('',title+'\n'+body)
    # Names can legitimately contain numerals; free-written numerical claims cannot.
    names=[p['player'] for ps in packet.get('observations',{}).get('player_statistics',{}).values() for p in ps]
    names += [m['opponent'] for m in packet['matches']]
    for name in sorted(names,key=len,reverse=True):raw=raw.replace(name,'NAME')
    unbound=re.search(r'\d+(?:\.\d+)?',raw) or NUMBER_WORDS.search(raw)
    if unbound:
        excerpt=raw[max(0,unbound.start()-45):unbound.end()+55].replace('\n',' ')
        raise ValueError('Unbound numerical claim: '+repr(excerpt)+'. Replace this claim with its verified phrase token or remove it')
    if re.search(r'\b(packet|ledger|profile data|material provided|documented assists)\b',raw,re.I):raise ValueError('Internal reporting language')
    if 'award' in facts and 'award' not in used:raise ValueError('Confirmed award omitted')
    return title,TOKEN.sub(lambda m:facts[m[1]],body)


def phrase_registry(packet):
    """Short, attributed fact phrases leave sentence structure to the reporter."""
    phrases={}
    words=['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty']
    def n(v):return words[int(v)] if int(v)==v and 0<=v<=20 else f'{v:g}'
    for kind in ('Official','Practice'):
        rows=[m for m in packet['matches'] if m['match_type']==kind and m['birmingham_score'] is not None and m['opponent_score'] is not None]
        if not rows:continue
        w=sum(m['birmingham_score']>m['opponent_score'] for m in rows);d=sum(m['birmingham_score']==m['opponent_score'] for m in rows);l=len(rows)-w-d
        phrases[kind+'_record']=f"{n(w)} {'win' if w==1 else 'wins'}, {n(d)} {'draw' if d==1 else 'draws'} and {n(l)} {'defeat' if l==1 else 'defeats'} across {n(len(rows))} {kind.lower()} matches"
        phrases[kind+'_goals']=f"Birmingham’s {n(sum(m['birmingham_score'] for m in rows))} goals scored and {n(sum(m['opponent_score'] for m in rows))} conceded in {kind.lower()}"
        for i,m in enumerate(rows):
            result='win over' if m['birmingham_score']>m['opponent_score'] else 'draw with' if m['birmingham_score']==m['opponent_score'] else 'defeat against'
            phrases[f'{kind}_match_{i}']=f"the {m['birmingham_score']}–{m['opponent_score']} {result} {m['opponent']}"
        for i,p in enumerate(packet.get('observations',{}).get('player_statistics',{}).get(kind,[])):
            name=p['player'];scope=f"across {n(p['appearances'])} {kind.lower()} appearances"
            if 'goals' in p or 'assists' in p:
                parts=[f"{n(p[k])} {label}" for k,label in [('goals','goals'),('assists','assists')] if k in p]
                phrases[f'{kind}_player_{i}_attack']=f"{name}’s "+' and '.join(parts)+' '+scope
            if 'average_rating' in p:phrases[f'{kind}_player_{i}_rating']=f"{name}’s average rating of {p['average_rating']:.2f} {scope}"
            for key,label in [('dribbles_completed','completed dribbles'),('saves','saves'),('tackles_won','tackles won'),('interceptions','interceptions')]:
                if p.get(key,0)>0:phrases[f'{kind}_player_{i}_{key}']=f"{name}’s {n(p[key])} {label} {scope}"
            if 'shots' in p and 'shots_on_target' in p:phrases[f'{kind}_player_{i}_shots']=f"{name}’s {n(p['shots_on_target'])} shots on target from {n(p['shots'])} attempts {scope}"
            if p.get('pass_accuracy') is not None:phrases[f'{kind}_player_{i}_passing']=f"{name}’s {p['pass_accuracy']:.1f}% pass completion ({p['passes_completed']:g} of {p['passes_attempted']:g} passes)"
    winner=(packet.get('management') or {}).get('player_name')
    if winner:phrases['award']=f'{winner}, Birmingham’s Player of the Week'
    return phrases
