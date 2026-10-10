"""Conservative parsing: unsupported formats remain raw, Unknown and reviewable."""
import re

SCORELINE = re.compile(r'^\s*(.+?)\s+(\d{1,2})\s*[-–:]\s*(\d{1,2})\s+(.+?)\s*$')
LABEL = re.compile(r'^\s*(opponent|birmingham score|opponent score)\s*:\s*(.*?)\s*$',re.I)


def normalize(text):
    return re.sub(r'\s+',' ',re.sub(r'[*_`#]','',text)).strip().casefold()


def parse_recap(text, club='Birmingham City'):
    club_names={normalize(club)}
    if normalize(club)=='birmingham city':
        club_names.add('mpl birmingham')
    found=[]
    for raw in text.splitlines():
        line=re.sub(r'[*_`]','',raw).strip()
        match=SCORELINE.fullmatch(line)
        if not match:
            continue
        home, hs, aws, away=match.groups()
        if normalize(home) in club_names and normalize(away) not in club_names:
            found.append({'opponent':away,'birmingham_score':int(hs),'opponent_score':int(aws)})
        elif normalize(away) in club_names and normalize(home) not in club_names:
            found.append({'opponent':home,'birmingham_score':int(aws),'opponent_score':int(hs)})
    if found:
        # Player blocks cannot safely be assigned across several scorelines.
        if len(found)==1:
            found[0]['statistics']=parse_player_stats(text)+parse_team_stats(text)
        return found
    fields={}
    for line in text.splitlines():
        match=LABEL.fullmatch(line)
        if match:
            key,value=match.groups()
            key=key.casefold().replace(' ','_')
            if key=='opponent':
                fields[key]=value or None
            elif value.isdigit():
                fields[key]=int(value)
    return [fields]  # Do not guess a score or classify based on keywords.


REGISTER = re.compile(r'^\s*(?:pep|gaffer(?:gpt)?)[,!]?\s+register me as (?:a |an )?(.+?) with (?:an? )?(.+?) role(?:\s+(?:with |on )?(.+?) focus)?[.!]?\s*$',re.I)


def parse_registration(text):
    match=REGISTER.fullmatch(text)
    return tuple(v.strip() if v else None for v in match.groups()) if match else None


PLAYER_HEADER=re.compile(r'^(.+?)\s+[—–]\s+(.+)$')
STAT_CELL=re.compile(r'^(RAT|GLS|SHT|AST|2AST|DRI|PAS|POS|TKL|INT|BLK|CLR|SVS):\s*(\d+(?:\.\d+)?(?:/\d+)?|-)$',re.I)
STAT_NAMES={'RAT':'rating','GLS':'goals','SHT':'shots','AST':'assists',
            '2AST':'secondary_assists','DRI':'dri','INT':'interceptions',
            'BLK':'blocks','CLR':'clearances','SVS':'saves'}


def parse_player_stats(text):
    # Explicit PLAYER STATS blocks only. Dashes mean unavailable, never invented zeroes.
    result=[]; active=False; player=None; values={}; invalid=set()
    def flush():
        if player:
            for metric,value in values.items():
                if metric not in invalid:
                    result.append({'subject_type':'player','subject_key':player,
                                   'metric':metric,'value':value,'unit':None,'source':'ourproclubs_text'})
    for raw in text.splitlines():
        line=re.sub(r'[*`]','',raw).strip()
        if line.upper()=='PLAYER STATS':
            active=True; continue
        if line.upper() in ('TEAM STATS','FINAL SCORE'):
            flush(); player=None; active=False; continue
        if not active:
            continue
        header=PLAYER_HEADER.fullmatch(line)
        if header:
            flush(); player=header.group(1).strip(); values={}; invalid=set(); continue
        if not player:
            continue
        for cell in line.split('|'):
            match=STAT_CELL.fullmatch(cell.strip())
            if not match:
                continue
            code,raw_value=match.groups(); code=code.upper()
            if raw_value=='-':
                continue
            metrics={}
            if code in ('PAS','TKL','POS'):
                if not re.fullmatch(r'\d+/\d+',raw_value):
                    continue
                first,second=map(int,raw_value.split('/'))
                if code in ('PAS','TKL') and first>second:
                    continue
                keys={'PAS':('passes_completed','passes_attempted'),
                      'TKL':('tackles_won','tackles_attempted'),
                      'POS':('pos_first','pos_second')}[code]
                metrics=dict(zip(keys,(first,second)))
            elif code in STAT_NAMES:
                value=float(raw_value)
                if code=='RAT' and not 0<=value<=10:
                    continue
                if code!='RAT' and not value.is_integer():
                    continue
                metrics={STAT_NAMES[code]:value}
            for metric,value in metrics.items():
                if metric in values and values[metric]!=value:
                    invalid.add(metric)
                values[metric]=value
    flush()
    return result



def parse_team_stats(text):
    # Explicit club totals only. Direction/length counts are not possession percentages.
    active=False; section=''; values={}; invalid=set()
    labels={'shots':'shots','shots conceded':'shots_conceded','chances created':'chances_created',
            'possession':'possession','pass accuracy':'pass_accuracy',
            'on target inside box':'shots_on_target_inside_box'}
    for raw in text.splitlines():
        line=re.sub(r'[*`]','',raw).strip()
        if line.upper()=='TEAM STATS': active=True; continue
        if line.upper()=='FINAL SCORE': active=False
        if not active: continue
        if ':' not in line:
            section=normalize(line).replace('—','-'); continue
        label,raw_value=line.split(':',1);label=normalize(label);raw_value=raw_value.strip()
        metric=labels.get(label)
        if not metric:
            if section in ('passing - direction','passing - length') and label in ('backwards','sideways','forwards','short','medium','long'):
                metric='passes_'+label
            elif section in ('possession won','possession lost') and label in ('defensive third','midfield third','attacking third'):
                metric=section.replace(' ','_')+'_'+label.replace(' ','_')
        match=re.fullmatch(r'(\d+(?:\.\d+)?)(%)?',raw_value)
        if not metric or not match: continue
        value=float(match.group(1));unit='%' if match.group(2) else 'count'
        if metric in ('possession','pass_accuracy') and (unit!='%' or value>100): continue
        if unit=='count' and not value.is_integer(): continue
        if metric in values and values[metric]!=(value,unit): invalid.add(metric)
        values[metric]=(value,unit)
    return [{'subject_type':'team','subject_key':'Birmingham City','metric':metric,
             'value':value,'unit':unit,'source':'ourproclubs_text'}
            for metric,(value,unit) in values.items() if metric not in invalid]
