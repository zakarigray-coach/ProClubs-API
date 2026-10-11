"""Source-backed article facts and deterministic validation; no provider or Discord IO."""
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from .excel_stats import player_totals


class ReportHold(ValueError):
    """A source problem that must be resolved before writing, not a proofreading task."""


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def source_identity(sheet):
    refs=dict(sheet.get('references',{}))
    period=next((f['value'] for f in sheet.get('facts',{}).values() if f['kind']=='period'),None)
    if period:refs['report:period']={'dates':period}
    return digest({'fixtures':sheet.get('fixtures',[]),'references':refs})


def match_day(value):
    try:return datetime.fromisoformat(value).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    except (ValueError,TypeError):return None


def build_fact_sheet(packet):
    rows=packet.get('source_matches',packet['matches'])
    fixtures=[];ids=set();facts={};references={};warnings=[]
    def add(kind,subject,metric,value,classification=None,fixture_id=None,sources=()):
        key=f'F{len(facts)+1:04d}'
        facts[key]={'kind':kind,'subject':subject,'metric':metric,'value':value,
                    'classification':classification,'fixture_id':fixture_id,'sources':list(sources)}
        return key
    for index,row in enumerate(rows):
        mid=row.get('match_id',index+1)
        if mid in ids:raise ReportHold(f'Match {mid} appears twice in the selection. Please confirm its selection.')
        ids.add(mid)
        kind=row.get('match_type')
        if kind not in ('Official','Practice'):
            raise ReportHold(f'Match {mid} is not classified for reporting. Is it official or practice?')
        own,other=row.get('birmingham_score'),row.get('opponent_score')
        if not row.get('opponent') or any(type(n) is not int or n<0 for n in (own,other)):
            raise ReportHold(f'Match {mid} has an incomplete opponent or score. What is the correct fixture and result?')
        ref=f'match:{mid}'
        references[ref]={k:row.get(k) for k in ('match_id','source_message_id','source_channel_id','source_guild_id','source_part','date_source','played_at','raw_recap')}
        references[ref]['raw_sha256']=digest(row.get('raw_recap',''))
        fixture={k:row.get(k) for k in ('played_at','opponent','venue','competition')}
        fixture.update(match_id=mid,match_type=kind,birmingham_score=own,opponent_score=other,
                       result='win' if own>other else 'draw' if own==other else 'defeat')
        fixtures.append(fixture)
        add('fixture',row['opponent'],'score',{'for':own,'against':other,'result':fixture['result'],
            'venue':row.get('venue','Unknown'),'competition':row.get('competition')},kind,mid,[ref])
    days=defaultdict(list)
    for row,fixture in zip(rows,fixtures):
        day=match_day(fixture['played_at'])
        if day and row.get('date_source') not in ('message','detected'):
            add('date',fixture['opponent'],'fixture_day',day,fixture['match_type'],fixture['match_id'],[f'match:{fixture["match_id"]}'])
            days[(fixture['match_type'],day)].append(fixture['match_id'])
    for (kind,day),mids in days.items():add('schedule','Birmingham City','fixtures_on_day',{'date':day,'count':len(mids)},kind,sources=[f'match:{mid}' for mid in mids])
    stats=[];unique={}
    for row in packet.get('statistics',[]):
        if row['match_id'] not in ids:continue
        key=tuple(row[k] for k in ('match_id','subject_type','subject_key','metric'))
        value=row['value']
        if not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ReportHold(f'Invalid {row["metric"]} value for {row["subject_key"]} in match {row["match_id"]}.')
        if key in unique:
            old=unique[key]
            if old['value']!=value or old.get('unit')!=row.get('unit'):
                raise ReportHold(f'Conflicting {row["metric"]} for {row["subject_key"]} in match {row["match_id"]}: '
                                 f'{old["value"]} ({old.get("source","unknown source")}) versus {value} ({row.get("source","unknown source")}). Which is correct?')
            continue
        unique[key]=row;stats.append(dict(row))
        references[f'stat:{len(stats)}']={k:row.get(k) for k in ('stat_id','match_id','subject_type','subject_key','metric','value','unit','source')}
    # The current source records, not cached aggregate prose, determine totals.
    groups={}
    by_id={m['match_id']:m for m in fixtures}
    for stat in stats:
        if stat['value']<0:raise ReportHold(f'Negative {stat["metric"]} for {stat["subject_key"]} in match {stat["match_id"]}.')
        if stat['subject_type']=='team' and stat['subject_key'].casefold() in ('birmingham city','mpl birmingham'):
            field={'goals':'birmingham_score','goals_scored':'birmingham_score','goals_conceded':'opponent_score'}.get(stat['metric'])
            if field and stat['value']!=by_id[stat['match_id']][field]:
                raise ReportHold(f'Match {stat["match_id"]} score and team {stat["metric"]} conflict: {by_id[stat["match_id"]][field]} versus {stat["value"]}. Which source is correct?')
    games=defaultdict(dict)
    for stat in stats:
        if stat['subject_type']=='player':games[(stat['match_id'],stat['subject_key'])][stat['metric']]=stat['value']
    for (mid,name),values in games.items():
        for numerator,denominator in [('passes_completed','passes_attempted'),('shots_on_target','shots')]:
            if numerator in values and denominator in values and values[numerator]>values[denominator]:
                raise ReportHold(f'{name} in match {mid}: {numerator} ({values[numerator]}) exceeds {denominator} ({values[denominator]}). Which figure is correct?')
    for kind in ('Official','Practice'):
        matches=[m for m in fixtures if m['match_type']==kind]
        if not matches:continue
        mids={m['match_id'] for m in matches}
        summary={'matches':len(matches),'wins':sum(m['result']=='win' for m in matches),
                 'draws':sum(m['result']=='draw' for m in matches),'losses':sum(m['result']=='defeat' for m in matches),
                 'goals_for':sum(m['birmingham_score'] for m in matches),'goals_against':sum(m['opponent_score'] for m in matches)}
        for metric,value in summary.items():add('team','Birmingham City',metric,value,kind,sources=[f'match:{mid}' for mid in sorted(mids)])
        players=player_totals([s for s in stats if s['match_id'] in mids])
        for player in players:
            name=player['player'];appearances=player['appearances']
            own=[s for s in stats if s['subject_type']=='player' and s['subject_key']==name and s['match_id'] in mids]
            sources=[key for key,s in references.items() if key.startswith('stat:') and s['subject_key']==name and s['match_id'] in mids]
            add('player',name,'appearances',appearances,kind,sources=sources)
            for metric,value in player.items():
                if metric in ('player','appearances','ratings','metric_samples','goalkeeper_appearances'):continue
                count=player['metric_samples'].get('rating' if metric=='average_rating' else metric)
                if metric=='pass_accuracy':count=appearances if value is not None else 0
                if count!=appearances:
                    warnings.append(f'{kind}: {name} {metric} has {count or 0}/{appearances} samples; omit complete-period claim.')
                    continue
                if metric in ('goals_conceded','clean_sheets') and player.get('goalkeeper_appearances')!=appearances:continue
                if value is None:continue
                rounded=round(value,2 if metric=='average_rating' else 1) if metric in ('average_rating','pass_accuracy') else value
                add('player',name,metric,rounded,kind,sources=sources)
            if all(player['metric_samples'].get(m)==appearances for m in ('goals','assists')):
                add('player',name,'goal_contributions',player.get('goals',0)+player.get('assists',0),kind,sources=sources)
            # Individual match evidence remains distinct from period totals.
            for s in own:
                if s['metric'] in ('goalkeeper_appearances','seconds_played'):continue
                if s['metric'] in ('goals_conceded','clean_sheets') and not any(x['metric']=='goalkeeper_appearances' and x['value']==1 and x['match_id']==s['match_id'] for x in own):continue
                add('player',name,s['metric'],s['value'],kind,s['match_id'],[f'match:{s["match_id"]}'])
        cached=packet.get('observations',{}).get('summaries',{}).get(kind,{})
        for metric in ('wins','draws','losses','goals_for','goals_against'):
            if metric in cached and cached[metric]!=summary[metric]:
                raise ReportHold(f'{kind} {metric} conflicts: selected fixtures total {summary[metric]}, cached analysis says {cached[metric]}. Please review the conflicting analysis.')
        cached_players=packet.get('observations',{}).get('player_statistics',{}).get(kind,[])
        for p in players:
            old=next((c for c in cached_players if c['player']==p['player']),None)
            if old:
                for metric in ('goals','assists','appearances','average_rating'):
                    if metric in old and metric in p and not math.isclose(old[metric],p[metric],rel_tol=1e-8,abs_tol=1e-8):
                        raise ReportHold(f'{p["player"]} {kind} {metric} conflicts: source rows {p[metric]}, cached total {old[metric]}. Please confirm the correct source.')
        if players and all(p['metric_samples'].get('goals')==p['appearances'] for p in players):
            recorded=sum(p.get('goals',0) for p in players)
            highest=max(p.get('goals',0) for p in players)
            if highest>0 and 0<=summary['goals_for']-recorded<highest:
                for p in players:
                    if p.get('goals')==highest:add('comparison',p['player'],'leading_scorer',True,kind,sources=[f'match:{mid}' for mid in sorted(mids)])
        selected=[m for m in fixtures if m['match_type']==kind]
        for result,metric in (('defeat','heaviest_defeat'),('win','largest_victory')):
            outcomes=[m for m in selected if m['result']==result]
            if outcomes:
                margin=max(abs(m['birmingham_score']-m['opponent_score']) for m in outcomes)
                for m in outcomes:
                    if abs(m['birmingham_score']-m['opponent_score'])==margin:
                        add('comparison',m['opponent'],metric,True,kind,m['match_id'],[f'match:{mid}' for mid in sorted(mids)])
        groups[kind]={'summary':summary,'players':players}
    management=packet.get('management') or {}
    if management.get('player_name'):add('award',management['player_name'],'player_of_week',True,sources=['management:award'])
    references['management:award']={'player_name':management.get('player_name'),'player_evidence':management.get('player_evidence')}
    if packet.get('period'):add('period','Reporting period','dates',packet['period'],sources=['report:period'])
    sheet={'version':1,'fixtures':fixtures,'groups':groups,'facts':facts,'references':references,
           'warnings':warnings,'quotes':[],'narrative_evidence':[],
           'excluded_names':packet.get('excluded_names',[])}
    sheet['source_hash']=source_identity(sheet)
    return sheet


WORDS={word:i for i,word in enumerate(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty'))}
NUMBER=r'\d+(?:\.\d+)?|'+ '|'.join(WORDS)
METRICS={
 'goal_contributions':r'goal (?:involvements?|contributions?)|direct contribution',
 'goals':r'goals?', 'assists':r'assists?', 'appearances':r'appearances?|run-outs?|outings|matches',
 'average_rating':r'(?:average\s+)?rating|average', 'rating':r'rating',
 'shots':r'shots?(?!\s+on target)', 'shots_on_target':r'shots? on target',
 'saves':r'saves?', 'dribbles_completed':r'(?:completed )?dribbles?',
 'passes_completed':r'(?:completed )?passes?', 'passes_attempted':r'passes?|attempts?',
 'pass_accuracy':r'%|per cent|passing|pass completion', 'tackles_won':r'(?:standing )?tackles?(?: won)?',
 'interceptions':r'interceptions?', 'wins':r'wins?|victories', 'draws':r'draws?',
 'losses':r'defeats?|losses', 'matches':r'matches|fixtures|games|game|match',
 'goals_for':r'goals(?: scored| for)?|scored|for', 'goals_against':r'goals(?: conceded| against)?|conceded|against',
 'goals_conceded':r'goals? conceded|conceded', 'clean_sheets':r'clean sheets?',
}


def number(value):return WORDS[value.casefold()] if value.casefold() in WORDS else float(value)


def numeric_spans(text,sheet):
    masked=text
    names={f['subject'] for f in sheet['facts'].values() if f['kind'] in ('player','fixture','award')}
    for name in sorted(names,key=len,reverse=True):
        masked=re.sub(re.escape(name),lambda m:' '*len(m[0]),masked)
    for match in re.finditer(r'\b(?:'+NUMBER+r')\b',masked,re.I):
        # Ordinary "one" is not always a numerical claim; metric context disambiguates.
        if match[0].casefold() in WORDS and not re.match(r'\s*[-–]?\s*(?:(?:practice|official|competitive|league|cup|friendly)\s+)?(?:'+ '|'.join(METRICS.values())+r')\b',masked[match.end():],re.I):continue
        yield match.start(),match.end(),number(match[0])


MONTHS=('January','February','March','April','May','June','July','August','September','October','November','December')
def date_spans(quote):
    for month,name in enumerate(MONTHS,1):
        for m in re.finditer(r'\b(\d{1,2})\s+('+name+r'|'+name[:3]+r')\b',quote,re.I):
            yield m.start(1),m.end(1),month,int(m[1])
        for m in re.finditer(r'\b('+name+r'|'+name[:3]+r')\s+(\d{1,2})\b',quote,re.I):
            yield m.start(2),m.end(2),month,int(m[2])


def validate_final(article,sheet,evidence):
    """The model locates claims; Python independently checks their referenced facts."""
    text=article['title']+'\n'+article['body'];facts=sheet['facts'];covered=set();fact_positions=defaultdict(set)
    if evidence.get('unsupported'):raise ValueError('Unsupported final claims: '+'; '.join(evidence['unsupported'])[:700])
    if re.search(r'[“”"]',text) and not sheet['quotes']:raise ValueError('Quotation has no verified source.')
    if re.search(r'\b(comeback|late winner|stoppage.time|dominat(?:ed|ing|ion)|tactical adjustment|changed (?:the )?formation)\b',text,re.I) and not sheet['narrative_evidence']:
        raise ValueError('Match narrative or tactical event lacks source evidence.')
    names={f['subject'] for f in facts.values() if f['kind'] in ('player','fixture','award')}
    for name in names:
        for occurrence in re.finditer(re.escape(name),text,re.I):
            if occurrence[0]!=name:raise ValueError('Preserve exact source name: '+name)
    for name in sheet['excluded_names']:
        if name not in names and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I):
            raise ValueError('Unselected fixture/player leaked into article: '+name)
    spans=list(numeric_spans(text,sheet))
    def scope_labels(segment):
        for name in sorted(names,key=len,reverse=True):segment=re.sub(re.escape(name),lambda m:' '*len(m[0]),segment,flags=re.I)
        return [m for m in re.finditer(r'\b(practice|friendly|friendlies|official|competitive|league|cup)\b',segment,re.I) if not re.search(r'(?:not|rather than|instead of|outside|away from)\s+(?:the\s+)?$',segment[:m.start()],re.I)]
    def scope_at(position):
        labels=scope_labels(text[:position])
        if not labels:return None
        return 'Practice' if labels[-1][0].lower() in ('practice','friendly','friendlies') else 'Official'
    for claim in evidence.get('claims',[]):
        key=claim.get('fact_id');quote=claim.get('quote','')
        if key not in facts or not quote or quote not in text:raise ValueError('Final claim lacks a valid fact reference or exact text span.')
        fact=facts[key];kind=fact['kind'];metric=fact['metric'];value=fact['value']
        start=text.index(quote);end=start+len(quote)
        candidates=[s for s in spans if start<=s[0] and s[1]<=end]
        if kind=='fixture':
            if fact['subject'] not in quote:raise ValueError('Fixture claim names the wrong opponent. Reference '+key+' requires '+fact['subject']+' in its exact quote: '+quote)
            score=value
            pairs=list(re.finditer(r'\b(\d{1,2})\s*[-–]\s*(\d{1,2})\b',quote))
            for pair in pairs:
                own,other=map(int,pair.groups())
                direct=(own,other)==(score['for'],score['against'])
                reverse=((own,other)==(score['against'],score['for']) and score['venue']=='Away'
                         and fact['subject'] in quote[:pair.start()] and re.search(r'Birmingham(?: City)?',quote[pair.end():]))
                if not (direct or reverse):continue
                nearby_scope=scope_at(start+pair.start())
                if nearby_scope and nearby_scope!=fact['classification']:continue
                if len(sheet['groups'])>1 and not nearby_scope:continue
                # Bind the score to its nearest named opponent, not merely any selected pair.
                opponents={m['opponent'] for m in sheet['fixtures']}
                positions=[(min(abs(p.start()-pair.start()),abs(p.end()-pair.end())),name) for name in opponents for p in re.finditer(re.escape(name),quote)]
                if positions and min(positions)[1]!=fact['subject']:continue
                context=quote.lower()
                result=score['result']
                wrong={'win':r'\b(?:lost|defeat)\b','defeat':r'\b(?:beat|victory|won)\b','draw':r'\b(?:beat|lost|victory|defeat)\b'}[result]
                if len(pairs)==1 and re.search(wrong,context):raise ValueError('Score/result contradiction for '+fact['subject'])
                covered.update((start+pair.start(1),start+pair.end(1)) for _ in [0])
                covered.add((start+pair.start(2),start+pair.end(2)))
        elif kind in ('date','schedule'):
            day=value if kind=='date' else value['date']
            wanted=datetime.fromisoformat(day)
            valid=[(a,b) for a,b,month,d in date_spans(quote) if (month,d)==(wanted.month,wanted.day)]
            if kind=='date' and fact['subject'] not in quote:continue
            if not valid:continue
            covered.update((start+a,start+b) for a,b in valid)
            covered.update((a,b) for a,b,n in candidates if n==wanted.year)
            if kind=='schedule':
                for a,b,n in candidates:
                    if n!=value['count'] or not re.search(r'\b(?:matches|fixtures|games)\b',text[b:min(end,b+35)],re.I):continue
                    scope=scope_at(a)
                    qualifier=re.match(r'\s+(practice|friendly|official|competitive|league|cup)\b',text[b:end],re.I)
                    if qualifier:scope='Practice' if qualifier[1].lower() in ('practice','friendly') else 'Official'
                    if scope and scope!=fact['classification']:continue
                    if len(sheet['groups'])>1 and not scope:continue
                    covered.add((a,b))
        elif kind=='comparison':
            if fact['subject'] not in quote:raise ValueError('Comparison names the wrong player.')
            labels=scope_labels(quote)
            scope=('Practice' if labels[-1][0].lower() in ('practice','friendly','friendlies') else 'Official') if labels else scope_at(start)
            if scope and scope!=fact['classification']:raise ValueError('Comparison mixes practice and competitive results.')
            if len(sheet['groups'])>1 and not scope:raise ValueError('Comparison requires an explicit practice or competitive scope.')
        elif kind=='period':
            if not re.search(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b|\d{4}-\d{2}-\d{2}',quote):continue
            allowed={v for _,_,v in numeric_spans(str(value),{'facts':{}})}
            covered.update((a,b) for a,b,v in candidates if v in allowed)
        elif kind in ('player','team'):
            if metric not in METRICS:raise ValueError('Unsupported metric in article: '+metric)
            if kind=='team' and metric=='matches' and list(date_spans(quote)):continue
            for a,b,n in candidates:
                if not math.isclose(float(value),n,abs_tol=0.011):continue
                previous=max([end_pos for begin,end_pos,_ in spans if end_pos<=a]+[start])
                following=min([begin for begin,_,_ in spans if begin>=b]+[end])
                window=text[max(start,previous,a-35):min(end,following,b+45)]
                if not re.search(METRICS[metric],window,re.I):continue
                if kind=='team':
                    actors={f['subject'] for f in facts.values() if f['kind']=='player'}|{'Birmingham City','Birmingham'}
                    context_start=max(0,text.rfind('\n\n',0,a)+2)
                    mentioned=[(p.start(),name) for name in actors for p in re.finditer(re.escape(name),text[context_start:a])]
                    if mentioned and max(mentioned)[1] not in ('Birmingham City','Birmingham'):continue
                if kind=='player':
                    if fact['fixture_id'] is not None:
                        fixture=next(m for m in sheet['fixtures'] if m['match_id']==fact['fixture_id'])
                        if fixture['opponent'] not in quote:continue
                        if re.search(r'\b(?:week|across|total|programme|period)\b',quote,re.I):continue
                        same=[m for m in sheet['fixtures'] if m['opponent']==fixture['opponent']]
                        if len(same)>1:
                            own,other=fixture['birmingham_score'],fixture['opponent_score']
                            identified=(fixture['venue'] in ('Home','Away') and re.search(r'\b'+fixture['venue']+r'\b',quote,re.I)) or re.search(r'\b'+str(own)+r'[-–]'+str(other)+r'\b',quote)
                            if not identified:continue
                    player_names={f['subject'] for f in facts.values() if f['kind']=='player'}
                    paragraph_start=max(0,text.rfind('\n\n',0,a)+2)
                    positions=[(p.start(),name) for name in player_names for p in re.finditer(re.escape(name),text[paragraph_start:a])]
                    if not positions and re.match(r'\s*(?:He|His|She|Her)\b',text[paragraph_start:a]):
                        previous_start=max(0,text.rfind('\n\n',0,max(0,paragraph_start-2))+2)
                        previous_text=text[previous_start:paragraph_start]
                        prior={name for name in player_names if name in previous_text}
                        if len(prior)==1:positions=[(0,next(iter(prior)))]
                    if not positions or max(positions)[1]!=fact['subject']:continue
                nearby_scope=scope_at(a)
                if nearby_scope and nearby_scope!=fact['classification']:continue
                if len(sheet['groups'])>1 and not nearby_scope:continue
                # Explicit nearby practice/official labels cannot contradict the source scope.
                para=text[max(0,text.rfind('\n\n',0,start)+2):end].lower()
                labels={m[0].lower() for m in scope_labels(para)}
                if fact['classification']=='Practice' and labels & {'official','competitive','league'}:continue
                if fact['classification']=='Official' and labels=={'practice'}:continue
                covered.add((a,b))
                if a>len(article['title']):fact_positions[key].add((a,b))
        elif kind=='award':
            player_names={f['subject'] for f in facts.values() if f['kind'] in ('player','award')}
            named={name for name in player_names if name in quote}
            if not named:
                paragraph_start=max(0,text.rfind('\n\n',0,start)+2)
                named={name for name in player_names if name in text[paragraph_start:start]}
                if not named and re.match(r'\s*(?:He|His|She|Her)\b',quote):
                    previous_start=max(0,text.rfind('\n\n',0,max(0,paragraph_start-2))+2)
                    named={name for name in player_names if name in text[previous_start:paragraph_start]}
            if named!={fact['subject']}:raise ValueError('Award recipient does not match management selection or is ambiguous.')
    used=defaultdict(set)
    for key,positions in fact_positions.items():
        f=facts[key]
        if positions and f['kind']=='player':used[(f['subject'],f['classification'],f['fixture_id'])].add(f['metric'])
    if any({'goals','assists','goal_contributions'}<=metrics for metrics in used.values()):
        raise ValueError('Do not repeat goals and assists as a combined goal-contribution total. Choose one presentation.')
    repeated=[key for key,positions in fact_positions.items() if len(positions)>1]
    if repeated:raise ValueError('Repeated statistical claims: '+', '.join(repeated))
    missing=[text[max(0,a-45):min(len(text),b+45)].replace('\n',' ') for a,b,_ in spans if (a,b) not in covered]
    if missing:raise ValueError('Final numeric claims lack correctly attributed source evidence: '+', '.join(missing)[:300])
    return {'source_hash':sheet['source_hash'],'article_hash':digest(article),
            'checks':['selected_fixtures','arithmetic','claim_attribution','numeric_coverage','names',
                      'classification_scope','quotation_sources','narrative_sources'],
            'claim_count':len(evidence.get('claims',[]))}
