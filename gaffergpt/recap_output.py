"""Content-only cover contract and Discord text from the same audited fact sheet.

All arithmetic belongs to report_verification, never the language model or renderer.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

FOOTER = 'RT Football Media • MPL Birmingham City'
LABELS = {'saves':'Saves','clean_sheets':'Clean sheets','goals':'Goals','assists':'Assists',
          'tackles_won':'Tackles won','interceptions':'Interceptions','blocks':'Blocks',
          'clearances':'Clearances','key_passes':'Key passes','passes_completed':'Passes completed',
          'pass_accuracy':'Pass accuracy','average_rating':'Avg rating','motm':'MOTM',
          'shots_on_target':'Shots on target','appearances':'Appearances'}


def select_player_stats(sheet, player, kind):
    # Only registered complete-period facts qualify; raw aggregates may be partial.
    available={f['metric']:(key,f) for key,f in sheet['facts'].items()
               if f['kind']=='player' and f['subject']==player and f['classification']==kind
               and f.get('fixture_id') is None and f['metric'] in LABELS}
    value=lambda metric: available.get(metric,('',{'value':0}))[1]['value'] or 0
    if value('saves')>0 or 'clean_sheets' in available:
        order=['saves','clean_sheets','average_rating','motm','pass_accuracy','appearances']
    elif value('goals')>0:
        order=['goals','assists','key_passes','average_rating','motm','shots_on_target','appearances']
    elif value('assists')>0 or value('key_passes')>0:
        order=['assists','key_passes','pass_accuracy','passes_completed','average_rating','appearances']
    else:
        order=['tackles_won','interceptions','blocks','clearances','pass_accuracy','passes_completed','average_rating','motm','appearances','goals','assists']
    order=[m for m in order if m!='appearances']+[m for m in LABELS if m not in order and m!='appearances']+['appearances']
    # Prefer meaningful positive contributions, retaining verified zero only as fallback.
    order=[m for m in order if m in available and value(m)>0]+[m for m in order if m in available and value(m)==0]
    return [dict(metric=m,label=LABELS[m],value=available[m][1]['value'],fact_id=available[m][0],
                 unit='%' if m=='pass_accuracy' else None) for m in order[:3]]


def checked_outputs(db, report_id, sample=False):
    from .report_audit import assert_current
    from .report_verification import digest
    from .weekly_intake import content
    from .competitions import report_event
    from .article_writer import period_label
    report=db.report(report_id)
    audit=db.one("SELECT fact_sheet,article_hash,started_at FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
    if not audit:raise ValueError('Generate a checked article before its cover payload.')
    body=report['article'].split('\n\n',1)[1].strip()
    if digest({'title':report['title'],'body':body})!=audit['article_hash']:
        raise ValueError('Article changed after verification.')
    sheet=json.loads(audit['fact_sheet']);assert_current(db,report_id,sheet)
    event=report_event(db,report_id) or {};supplied=content(db,report_id)
    kind='Cup' if event.get('report_type')=='Cup' else 'Practice' if sample else 'Official'
    if set(sheet['groups'])!={kind}:raise ValueError('Select one competition scope for the cover and article.')
    summary=sheet['groups'][kind]['summary'];player=supplied.get('player_name') or None
    stats=select_player_stats(sheet,player,kind)
    # Short cover copy is deterministic editorial content, independent of the long article title.
    if summary['losses']==0 and summary['wins']>0:headline='Blues Keep Defeat At Bay'
    elif summary['wins']>0:headline='Blues Find Mixed Fortunes'
    elif summary['draws']>0:headline='Blues Held In The Balance'
    else:headline='Blues Face A Tough Return'
    if kind=='Cup':headline='Blues Under The Cup Spotlight'
    deck=f"{summary['goals_for']} scored, {summary['goals_against']} conceded across {summary['matches']} matches."
    payload={'schema_version':1,'report_id':report_id,'source_hash':sheet['source_hash'],
             'report_date':datetime.fromisoformat(audit['started_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat(),'date_range':{'start':report['week_start'],'end':report['week_end'],'end_exclusive':True,'timezone':'America/New_York'},
             'period':period_label(report),'report_label':'CUP EDITION' if kind=='Cup' else 'SAMPLE • PRACTICE' if sample else 'MPL WEEKLY RECAP',
             'competition':event.get('name') or 'MPL Birmingham City',
             'headline':headline,'supporting_headline':deck,
             'record':{key:summary[key] for key in ('wins','draws','losses')},
             'goals':{'scored':summary['goals_for'],'conceded':summary['goals_against']},
             'player_of_the_week':{'name':player,'award_label':event.get('award_label','Cup Standout') if kind=='Cup' else 'Player of the Week',
                 'photo_reference':f'/reports/{report_id}/photo' if supplied.get('photo') else None,'statistics':stats},
             'missing_information':([] if player else ['Player of the Week selection'])+([] if len(stats)==3 else ['Fewer than three verified player statistics'])}
    editorial=db.one('SELECT reporter FROM report_editorial WHERE report_id=?',(report_id,)) or {'reporter':'Raine'}
    article='\n\n'.join([report['title'],f"By {editorial['reporter']} | RT Football Media",period_label(report),
        'APPROVED' if report['status']=='approved' else 'DRAFT — awaiting Coach review',body,FOOTER])
    discord_chunks(article)  # Validate before sending any cover or text.
    return payload,article


def discord_chunks(article, limit=2000):
    """Paragraph boundaries only; reject a paragraph that needs editorial shortening."""
    chunks=[];current=''
    for paragraph in article.strip().split('\n\n'):
        if len(paragraph.encode('utf-16-le'))//2>limit:
            raise ValueError('A paragraph exceeds Discord’s message limit; shorten it before delivery.')
        candidate=current+'\n\n'+paragraph if current else paragraph
        if len(candidate.encode('utf-16-le'))//2>limit:
            chunks.append(current);current=paragraph
        else:current=candidate
    if current:chunks.append(current)
    return chunks
