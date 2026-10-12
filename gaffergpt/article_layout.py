"""Approved RT masthead, fixed typography and featured-player placement; no image AI."""
import io
import json
from datetime import datetime
from PIL import Image,ImageDraw,ImageOps
from .cup_cover import ASSETS,NAVY,BLUE,WHITE,font,wrap,text_block


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def weekly_cover(title,period,summary,player=None,photo=None,statistics=None,sample=False,payload=None):
    image=Image.new('RGB',(1080,760),NAVY);draw=ImageDraw.Draw(image)
    # Original approved brushstroke artwork stays intact; featured photo stays on the right.
    with Image.open(ASSETS/'rt-media-masthead.jpg') as source:
        masthead=ImageOps.contain(source.convert('RGB'),(992,224));image.paste(masthead,((1080-masthead.width)//2,25))
    text_block(draw,((payload or {}).get('report_label') or ('SAMPLE • HISTORICAL PRACTICE DATA' if sample else 'MPL BIRMINGHAM CITY • WEEKLY EDITION')),(44,266,992,50),24,True,colour='#63c9ff')
    text_block(draw,period,(44,313,610,55),24)
    pages=[]
    try:text_block(draw,title,(44,396,602,156 if payload else 216),54,True,max_lines=2 if payload else 3)
    except ValueError:
        # Complete headline moves to the article card instead of shrinking or clipping.
        words={3:'Three',4:'Four',5:'Five',6:'Six',7:'Seven',8:'Eight',9:'Nine',10:'Ten'}
        goals=(statistics or {}).get('goals')
        short=(words.get(goals,f'{goals:g}')+' goals. One standout week.') if player and goals is not None and goals>=3 else f"{summary['wins']} {'win' if summary['wins']==1 else 'wins'} from Birmingham’s week"
        text_block(draw,short,(44,396,602,216),54,True,max_lines=3)
    if payload:text_block(draw,payload['supporting_headline'],(44,552,602,68),22,max_lines=2)
    record=' • '.join(str(summary[k])+' '+(label if summary[k]==1 else label+'S') for k,label in [('wins','WIN'),('draws','DRAW'),('losses','DEFEAT')])
    draw.rectangle((44,624,650,723),fill=BLUE)
    text_block(draw,record,(60,638,574,40),24,True)
    text_block(draw,f"{summary['goals_for']} SCORED / {summary['goals_against']} CONCEDED",(60,681,574,34),22)
    draw.rectangle((695,310,1036,724),fill=BLUE,outline='#63c9ff',width=2)
    label=payload['player_of_the_week']['award_label'].upper() if payload else 'PLAYER OF THE WEEK' if player else 'FEATURED PLAYER'
    if label=='PLAYER OF THE TOURNAMENT':label='TOURNAMENT PLAYER'
    text_block(draw,label,(711,325,309,48),22,True)
    if photo:
        with Image.open(io.BytesIO(photo)) as source:
            image.paste(ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'),(305,214)),(713,380))
    else:text_block(draw,'PHOTO OPTIONAL',(718,452,290,55),24,True)
    if player:
        try:text_block(draw,player,(712,606,307,58),26,True,max_lines=1)
        except ValueError:text_block(draw,'Featured player',(712,606,307,58),26,True)
        stats=statistics or {};figures=[]
        for key,label in [('goals','G'),('assists','A'),('average_rating','RTG')]:
            if stats.get(key) is not None:figures.append((f'{stats[key]:.2f}' if key=='average_rating' else f'{stats[key]:g}')+' '+label)
        if payload:
            abbreviations={'saves':'SV','clean_sheets':'CS','goals':'G','assists':'A','tackles_won':'TKL','interceptions':'INT','blocks':'BLK','clearances':'CLR','key_passes':'KP','pass_accuracy':'','passes_completed':'PC','average_rating':'RTG','motm':'MOTM','appearances':'APP','shots_on_target':'SOT'}
            figures=[f"{item['value']:g}{item['unit'] or ''}{abbreviations[item['metric']]}" for item in payload['player_of_the_week']['statistics']]
        if figures:text_block(draw,(' ' if payload else ' • ').join(figures),(711,677,309,40),23,True)
    return png(image)


def article_pages(title,body,reporter,period):
    """Readable continuation cards preserve every word and paragraph, with measured bounds."""
    probe=ImageDraw.Draw(Image.new('RGB',(1080,1560)));head=font(36,True);face=font(28)
    # Long tokens are uncommon gamertags; fail rather than crop them silently.
    headline=wrap(probe,title,head,984)
    chunks=[]
    for paragraph in body.split('\n\n'):
        if paragraph.strip():chunks.extend(wrap(probe,paragraph,face,984)+[''])
    pages=[];offset=0;page_number=1
    while offset<len(chunks) or not pages:
        image=Image.new('RGB',(1080,1560),NAVY);draw=ImageDraw.Draw(image)
        with Image.open(ASSETS/'rt-media-masthead.jpg') as source:
            masthead=ImageOps.contain(source.convert('RGB'),(984,224));image.paste(masthead,((1080-masthead.width)//2,25))
        y=284
        if page_number==1:
            for line in headline:
                if y+48>850:raise ValueError('The article headline is too long for its readable layout.')
                draw.text((48,y),line,font=head,fill=WHITE,anchor='lt');y+=48
            for line in wrap(draw,'By '+reporter+' | RT Football Media • '+period,font(22),984):
                draw.text((48,y),line,font=font(22),fill='#63c9ff',anchor='lt');y+=34
            y+=20
        while offset<len(chunks) and y+40<=1460:
            line=chunks[offset]
            if line:
                bounds=draw.textbbox((48,y),line,font=face,anchor='lt')
                if bounds[2]>1032 or bounds[3]>1460:raise ValueError('Article text would clip.')
                draw.text((48,y),line,font=face,fill=WHITE,anchor='lt')
            y+=40;offset+=1
        text_block(draw,f'RT FOOTBALL MEDIA • PAGE {page_number}',(48,1495,984,42),22,True,colour='#63c9ff')
        pages.append(png(image));page_number+=1
        if page_number>7:raise ValueError('This article exceeds Discord attachment limits. Shorten it before delivery.')
    return pages


def media_pages(db,report_id,sample=False):
    try:return _media_pages(db,report_id,sample)
    except (OSError,Image.DecompressionBombError) as error:
        raise ValueError('The featured photo could not be rendered. Attach a valid PNG, JPEG or WebP; the verified article is still saved.') from error


def _media_pages(db,report_id,sample=False):
    from .recap_output import checked_outputs
    from .weekly_intake import content
    payload,article=checked_outputs(db,report_id,sample)
    supplied=content(db,report_id)
    summary=dict(payload['record'],goals_for=payload['goals']['scored'],goals_against=payload['goals']['conceded'])
    return [weekly_cover(payload['headline'],payload['period'],summary,
        payload['player_of_the_week']['name'],supplied.get('photo'),sample=sample,payload=payload)]
