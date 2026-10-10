"""Conservative parsing: unsupported formats remain raw, Unknown and reviewable."""
import re

SCORELINE = re.compile(r'^\s*(.+?)\s+(\d{1,2})\s*[-–:]\s*(\d{1,2})\s+(.+?)\s*$')
LABEL = re.compile(r'^\s*(opponent|birmingham score|opponent score)\s*:\s*(.*?)\s*$',re.I)


def normalize(text):
    return re.sub(r'\s+',' ',re.sub(r'[*_`#]','',text)).strip().casefold()


def parse_recap(text, club='Birmingham City'):
    club_name=normalize(club)
    found=[]
    for raw in text.splitlines():
        line=re.sub(r'[*_`]','',raw).strip()
        match=SCORELINE.fullmatch(line)
        if not match:
            continue
        home, hs, aws, away=match.groups()
        if normalize(home)==club_name and normalize(away)!=club_name:
            found.append({'opponent':away,'birmingham_score':int(hs),'opponent_score':int(aws)})
        elif normalize(away)==club_name and normalize(home)!=club_name:
            found.append({'opponent':home,'birmingham_score':int(aws),'opponent_score':int(hs)})
    if found:
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
