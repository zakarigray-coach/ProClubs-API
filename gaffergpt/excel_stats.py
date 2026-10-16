"""Carry exact spreadsheet stats into selected match records and weekly reporting."""
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

PLAYER_METRICS={'Rating':'rating','Goals':'goals','Assists':'assists','Shots':'shots','Passes made':'passes_completed','Pass attempts':'passes_attempted','Tackles made':'tackles_won','Tackle attempts':'tackles_attempted','Saves':'saves','Goals conceded':'goals_conceded','Red cards':'red_cards','Clean sheet':'clean_sheets','MOTM':'motm','Interceptions':'interceptions','Dribbles':'dribbles','Dribbles completed':'dribbles_completed','Second assists':'second_assists','Key passes':'key_passes','Standing tackles won':'standing_tackles_won','Sliding tackles won':'sliding_tackles_won','Fouls committed':'fouls_committed','Possessions won':'possessions_won','Possessions lost':'possessions_lost','Blocks':'blocks','Clears':'clearances','Shots on target':'shots_on_target','Yellow cards':'yellow_cards','Fouls won':'fouls_won','Aerial duels won':'aerial_duels_won','Seconds played':'seconds_played'}
TEAM_METRICS={'Shots':'shots','Passes made':'passes_completed','Pass attempts':'passes_attempted','Pass %':'pass_accuracy','Tackles made':'tackles_won','Tackle attempts':'tackles_attempted','Tackle %':'tackle_success','Saves':'saves','Red cards':'red_cards','Opponent shots':'shots_conceded','Players':'players'}

def records(workbook,sheet_name):
    for sheet in json.loads(workbook)['worksheets']:
        if sheet['sheet'].casefold()==sheet_name.casefold() and sheet['rows']:
            headers=sheet['rows'][0]
            return [dict(zip(headers,row)) for row in sheet['rows'][1:]]
    return []

def match_key(row,stored=False):
    try:
        date=datetime.fromisoformat(row['played_at'] if stored else row['Date'])
        day=date.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        opponent=row['opponent'] if stored else row['Opponent']
        return(day,' '.join(opponent.split()).casefold(),row['birmingham_score'] if stored else row['Goals for'],row['opponent_score'] if stored else row['Goals against'])
    except (KeyError,TypeError,ValueError,AttributeError):return None

def imported_statistics(workbook,matches):
    source=defaultdict(list);saved=defaultdict(list)
    for row in records(workbook,'Matches'):
        key=match_key(row)
        if key:source[key].append(row)
    for row in matches:
        key=match_key(row,True)
        if key:saved[key].append(row)
    mapping={};statistics=[]
    for key,targets in saved.items():
        rows=source.get(key,[])
        if len(rows)!=1 or len(targets)!=1:continue # Ambiguous rows must not receive another match's stats.
        for row,target in zip(rows,sorted(targets,key=lambda m:m['match_id'])):
            source_id=str(row.get('Match ID',''))
            if not source_id:continue
            mapping[source_id]=target['match_id']
            for label,metric in TEAM_METRICS.items():
                val=row.get(label)
                if type(val) not in (int,float) or not math.isfinite(val):continue
                statistics.append((target['match_id'],'team','Birmingham City',metric,float(val)*100 if label.endswith('%') else float(val),'%' if label.endswith('%') else None,'PCT+ Excel'))
    for row in records(workbook,'Player matches'):
        mid=mapping.get(str(row.get('Match ID','')));name=row.get('Player')
        if not mid or not isinstance(name,str) or not name.strip():continue
        is_keeper=str(row.get('Position','')).strip().casefold() in ('gk','goalkeeper','keeper')
        statistics.append((mid,'player',name.strip(),'goalkeeper_appearances',float(is_keeper),None,'PCT+ Excel'))
        for label,metric in PLAYER_METRICS.items():
            if metric in ('goals_conceded','clean_sheets') and not is_keeper:continue
            val=row.get(label)
            if type(val) not in (int,float,bool) or not math.isfinite(val):continue
            statistics.append((mid,'player',name.strip(),metric,float(val),None,'PCT+ Excel'))
    return statistics

def save_excel_statistics(db,workbook,matches):
    stats=imported_statistics(workbook,matches)
    with db.connect() as conn:
        conn.executemany('''INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,unit,source) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(match_id,subject_type,subject_key,metric) DO UPDATE SET value=excluded.value,unit=excluded.unit,source=excluded.source''',stats)
    return len(stats)

def player_totals(statistics):
    games=defaultdict(dict)
    for s in statistics:
        if s['subject_type']=='player':games[(s['subject_key'],s['match_id'])][s['metric']]=s['value']
    totals={}
    for (name,mid),stats in games.items():
        if stats.get('seconds_played')==0:continue
        target=totals.setdefault(name,{'player':name,'appearances':0,'ratings':[],'metric_samples':{}})
        target['appearances']+=1
        for metric,value in stats.items():
            if metric=='rating':target['ratings'].append(value)
            else:target[metric]=target.get(metric,0)+value
            target['metric_samples'][metric]=target['metric_samples'].get(metric,0)+1
    for player in totals.values():
        if player['ratings']:player['average_rating']=sum(player['ratings'])/len(player['ratings'])
        if player.get('passes_attempted',0)>0 and player['metric_samples'].get('passes_completed')==player['appearances'] and player['metric_samples'].get('passes_attempted')==player['appearances']:player['pass_accuracy']=100*player.get('passes_completed',0)/player['passes_attempted'] if 'passes_completed' in player else None
    return sorted(totals.values(),key=lambda p:(-(p.get('goals',0)+p.get('assists',0)),p['player'].casefold()))

def stats_text(players):
    lines=['PLAYER STATS — SELECTED MATCHES ONLY','Missing statistics stay unavailable; appearances with explicitly zero seconds played are excluded.']
    for p in players:
        parts=[f"{p['appearances']} appearances"]
        for key,label in [('goals','goals'),('assists','assists'),('shots','shots'),('shots_on_target','shots on target'),('tackles_won','tackles won'),('interceptions','interceptions'),('saves','saves'),('motm','MOTM awards')]:
            if key in p:parts.append(f"{p[key]:g} {label}")
        if 'average_rating' in p:parts.append(f"{p['average_rating']:.2f} average rating ({len(p['ratings'])} recorded ratings)")
        if p.get('pass_accuracy') is not None:parts.append(f"{p['pass_accuracy']:.1f}% passing ({p.get('passes_completed',0):g}/{p['passes_attempted']:g})")
        lines.append(p['player']+': '+', '.join(parts)+'.')
    return '\n'.join(lines)
