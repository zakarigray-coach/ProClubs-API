"""Fixed CUP EDITION template: original masthead, measured text, no image AI."""
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ASSETS=Path(__file__).parent/'assets'
SIZE=(1080,1560)
NAVY='#07172e';BLUE='#163f77';GOLD='#d9b66b';WHITE='#f4f7fb'


def font(size,bold=False):
    name='DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    bundled=ASSETS/'fonts'/name
    path=bundled if bundled.exists() else Path('/usr/share/fonts/truetype/dejavu')/name
    return ImageFont.truetype(str(path),size)


def wrap(draw,text,face,width):
    lines=[];line=''
    for word in str(text).split():
        if draw.textlength(word,font=face)>width:raise ValueError('Cover word is too wide; use a shorter cover headline.')
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=face)>width:
            lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines


def text_block(draw,text,box,size,bold=False,colour=WHITE,max_lines=None):
    x,y,w,h=box;face=font(size,bold);lines=wrap(draw,text,face,w);step=size+12
    if len(lines)*step>h or (max_lines and len(lines)>max_lines):
        raise ValueError('Cover text does not fit at the approved readable size; shorten the cover headline or use another card.')
    for line in lines:
        bounds=draw.textbbox((x,y),line,font=face,anchor='lt')
        if bounds[2]>x+w or bounds[3]>box[1]+h:raise ValueError('Cover text clips its allotted panel.')
        draw.text((x,y),line,font=face,fill=colour,anchor='lt');y+=step
    return lines


def render(event,headline,player=None,photo=None,sample=False):
    if event.get('report_type')!='Cup':raise ValueError('CUP EDITION requires a cup competition.')
    image=Image.new('RGB',SIZE,NAVY);draw=ImageDraw.Draw(image)
    # Preserve the approved artwork intact, including its original lettering.
    with Image.open(ASSETS/'rt-media-masthead.jpg') as original:
        masthead=ImageOps.contain(original.convert('RGB'),(984,224))
        image.paste(masthead,((1080-masthead.width)//2,35))
    draw.rectangle((48,280,1032,344),fill=GOLD)
    text_block(draw,'SAMPLE • CUP EDITION' if sample else 'CUP EDITION',(72,292,936,48),32,True,colour=NAVY)
    text_block(draw,event['name'],(48,378,984,160),40,True,max_lines=3)
    from datetime import date
    dates=date.fromisoformat(event['event_start']).strftime('%d %B %Y').lstrip('0') if event.get('event_start') else 'Date unconfirmed'
    if event.get('event_end') and event['event_end']!=event.get('event_start'):dates+=' – '+date.fromisoformat(event['event_end']).strftime('%d %B %Y').lstrip('0')
    text_block(draw,dates,(48,542,984,58),28,colour=GOLD)
    text_block(draw,headline,(48,630,984,300),54,True,max_lines=4)
    draw.line((48,960,1032,960),fill=GOLD,width=3)
    # Featured-player panel never implies a photograph exists when none was supplied.
    panel=(48,1010,388,1450);draw.rectangle(panel,fill=BLUE)
    if photo:
        with Image.open(io.BytesIO(photo)) as src:
            src=ImageOps.exif_transpose(src).convert('RGB')
            image.paste(ImageOps.fit(src,(340,440)),(48,1010))
    else:
        text_block(draw,'FEATURED PLAYER\nPHOTO OPTIONAL',(75,1170,285,170),26,True)
    label=event.get('award_label','Cup Standout')
    if label=='Player of the Tournament' and not event.get('award_scope'):
        raise ValueError('Player of the Tournament needs confirmed award scope.')
    if player:
        text_block(draw,label.upper(),(426,1020,606,120),28,True,colour=GOLD)
        text_block(draw,player,(426,1150,606,170),38,True)
    outcome=event.get('outcome','Unknown')
    if outcome!='Unknown':
        if not event.get('outcome_evidence') or not event.get('format'):raise ValueError('Cover outcome is unverified.')
        text_block(draw,outcome.upper(),(426,1340,606,100),30,True,colour=GOLD)
    elif event.get('stage_label'):
        text_block(draw,event['stage_label'],(426,1340,606,100),30,True,colour=GOLD)
    text_block(draw,'MPL BIRMINGHAM CITY • RT FOOTBALL MEDIA',(48,1490,984,52),24,True)
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


def report_cover(db,report_id):
    from .competitions import report_event
    from .weekly_intake import content
    from .report_audit import assert_current
    import json
    event=report_event(db,report_id)
    if not event or event['report_type']!='Cup':return None
    report=db.report(report_id)
    audit=db.one("SELECT fact_sheet,article_hash FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
    if not audit:raise ValueError('Generate a checked cup article before its cover.')
    from .report_verification import digest
    saved=db.report(report_id)
    if not saved.get('article') or digest({'title':saved['title'],'body':saved['article'].split('\n\n',1)[1].strip()})!=audit['article_hash']:
        raise ValueError('The cup article changed after validation; generate a fresh draft.')
    assert_current(db,report_id,json.loads(audit['fact_sheet']))
    supplied=content(db,report_id)
    return render(event,report['title'],supplied.get('player_name'),supplied.get('photo'))


def render_pages(event,headline,player=None,photo=None,sample=False):
    """Long text moves to a second card; it never silently loses words or shrinks."""
    try:return [render(event,headline,player,photo,sample)]
    except ValueError as error:
        if not any(s in str(error) for s in ('Cover text','Cover word')):raise
    compact=dict(event,name='Cup / Tournament',stage_label=None)
    first=render(compact,'Birmingham City — cup edition',None,photo,sample)
    text=event['name']+'\n\n'+headline
    if player:text+='\n\n'+event.get('award_label','Cup Standout')+': '+player
    if event.get('stage_label'):text+='\n\n'+event['stage_label']
    pages=[first];face=font(40,True);probe=ImageDraw.Draw(Image.new('RGB',SIZE))
    lines=[]
    for para in text.split('\n\n'):lines.extend(wrap(probe,para,face,984)+[''])
    for offset in range(0,len(lines),19):
        image=Image.new('RGB',SIZE,NAVY);draw=ImageDraw.Draw(image)
        text_block(draw,'SAMPLE • CUP EDITION' if sample else 'CUP EDITION',(48,48,984,60),32,True,colour=GOLD)
        y=180
        for line in lines[offset:offset+19]:
            if line:draw.text((48,y),line,font=face,fill=WHITE,anchor='lt')
            y+=60
        out=io.BytesIO();image.save(out,format='PNG');pages.append(out.getvalue())
    return pages


def report_covers(db,report_id):
    from .competitions import report_event
    from .weekly_intake import content
    event=report_event(db,report_id)
    if not event or event['report_type']!='Cup':return []
    # Perform the same current-source audit before any card leaves the service.
    from .report_audit import assert_current
    import json
    audit=db.one("SELECT fact_sheet,article_hash FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
    if not audit:raise ValueError('Generate a checked cup article before its cover.')
    from .report_verification import digest
    saved=db.report(report_id)
    if not saved.get('article') or digest({'title':saved['title'],'body':saved['article'].split('\n\n',1)[1].strip()})!=audit['article_hash']:
        raise ValueError('The cup article changed after validation; generate a fresh draft.')
    assert_current(db,report_id,json.loads(audit['fact_sheet']))
    supplied=content(db,report_id)
    from .competitions import snapshot
    stages=list(dict.fromkeys(d['stage'] for d in snapshot(db,report_id)['match_details'] if d.get('stage') and d['stage'].lower()!='unknown'))
    if stages:event=dict(event,stage_label=' / '.join(stages))
    return render_pages(event,db.report(report_id)['title'],supplied.get('player_name'),supplied.get('photo'))
