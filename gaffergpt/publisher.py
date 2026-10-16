"""Publish one approved report to Discord as RT Football Media, exactly once.

Posts over Discord's REST API with RT Media's own token, so the public post
carries the newsroom identity while approval stays with Coach.
"""
import asyncio
import json
from datetime import datetime
import aiohttp
from .database import utcnow

API='https://discord.com/api/v10'
FORUM_TYPES=(15,16)  # forum and media channels hold posts, not bare messages
DISCORD_EPOCH=1420070400000
SCHEMA='''CREATE TABLE IF NOT EXISTS report_publications (
 report_id INTEGER PRIMARY KEY REFERENCES weekly_reports(report_id),
 channel_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('publishing','published')),
 message_ids TEXT NOT NULL DEFAULT '[]', claimed_at TEXT NOT NULL, published_at TEXT
);'''


LOCK=asyncio.Lock()


class PublishError(ValueError):
    pass


def publication(db,report_id):
    with db.connect() as conn:conn.executescript(SCHEMA)
    return db.one('SELECT * FROM report_publications WHERE report_id=?',(report_id,))


def public_messages(db,report_id):
    """Cover image first, then the article as plain Discord text. No AI calls."""
    from .article_layout import media_pages
    from .recap_output import checked_outputs,discord_chunks
    _,article=checked_outputs(db,report_id)
    # The review-status line is for Coach's preview only.
    article='\n\n'.join(p for p in article.split('\n\n') if p not in ('APPROVED','DRAFT — awaiting Coach review'))
    return media_pages(db,report_id),discord_chunks(article)


async def discord_post(token,channel_id,content,images,nonce,title=None):
    """Send one message, or open a forum post when a title is given.

    The enforced nonce makes Discord drop an accidental repeat. Forum posts take no
    nonce, so discord_forum looks for an earlier attempt before one is opened.
    """
    payload={'content':content,'allowed_mentions':{'parse':[]},
             'attachments':[{'id':i,'filename':f'RT_Media_{i+1}.png'} for i in range(len(images))]}
    if title:path,payload='threads',{'name':title,'message':payload}
    else:path='messages';payload.update(nonce=nonce,enforce_nonce=True)
    form=aiohttp.FormData();form.add_field('payload_json',json.dumps(payload),content_type='application/json')
    for i,data in enumerate(images):
        form.add_field(f'files[{i}]',data,filename=f'RT_Media_{i+1}.png',content_type='image/png')
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(f'{API}/channels/{channel_id}/{path}',data=form,headers={'Authorization':'Bot '+token}) as response:
            if response.status>=300:
                raise PublishError(f'Discord refused the post (status {response.status}). Nothing further was sent.')
            return (await response.json())['id']


async def discord_forum(token,channel_id,title=None,since=None):
    """Returns (is a forum, ID of the post this report already opened there)."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60),headers={'Authorization':'Bot '+token}) as session:
        async def get(path):
            async with session.get(API+path) as response:
                if response.status>=300:
                    raise PublishError(f'Discord would not show the publish channel (status {response.status}). Nothing was sent.')
                return await response.json()
        channel=await get(f'/channels/{channel_id}')
        if channel.get('type') not in FORUM_TYPES:return False,None
        if not title:return True,None
        # A post's ID carries its creation time; allow a minute for clock difference.
        earliest=datetime.fromisoformat(since).timestamp()*1000-60000
        for thread in (await get(f"/guilds/{channel['guild_id']}/threads/active"))['threads']:
            if (thread.get('parent_id')==str(channel_id) and thread['name']==title
                    and (int(thread['id'])>>22)+DISCORD_EPOCH>=earliest):
                return True,thread['id']
        return True,None


async def publish_report(db,report_id,token,channel_id,post=discord_post,forum=discord_forum):
    """Returns (message_ids, newly_published, link path). A report can only ever be published once."""
    # One publish at a time, so a double-tap cannot start two sends.
    async with LOCK:
        return await _publish(db,report_id,token,channel_id,post,forum)


async def _where(forum,token,channel_id,ids):
    # In a forum the first message shares its ID with the post it opened.
    return f'{ids[0]}/{ids[0]}' if (await forum(token,channel_id))[0] else f'{channel_id}/{ids[0]}'


async def _publish(db,report_id,token,channel_id,post,forum):
    if not token or not channel_id:
        raise PublishError('Publishing is not configured. Set RT_MEDIA_DISCORD_TOKEN and RT_MEDIA_PUBLISH_CHANNEL_ID.')
    report=db.report(report_id)
    if not report or report['status']!='approved':
        raise PublishError('Approve this draft before publishing.')
    saved=publication(db,report_id)
    if saved and saved['state']=='published':
        ids=json.loads(saved['message_ids'])
        return ids,False,await _where(forum,token,saved['channel_id'],ids)
    images,chunks=public_messages(db,report_id)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT OR IGNORE INTO report_publications(report_id,channel_id,state,claimed_at) VALUES (?,?,'publishing',?)",
                     (report_id,str(channel_id),utcnow()))
        row=conn.execute('SELECT * FROM report_publications WHERE report_id=?',(report_id,)).fetchone()
    if row['state']=='published':
        ids=json.loads(row['message_ids'])
        return ids,False,await _where(forum,token,row['channel_id'],ids)
    if row['channel_id']!=str(channel_id):
        raise PublishError('This report was already started in another channel. Check that channel before retrying.')
    sent=json.loads(row['message_ids'])
    # A forum post is titled with the headline, so the headline is not repeated in its text.
    headline,_,rest=chunks[0].partition('\n\n');title=headline[:100]
    is_forum,opened=await forum(token,channel_id,None if sent else title,row['claimed_at'])
    if is_forum and rest and title==headline:chunks[0]=rest
    if opened:
        sent=[opened];db.execute('UPDATE report_publications SET message_ids=? WHERE report_id=?',(json.dumps(sent),report_id))
    # Resume after an interrupted publish: messages already recorded are never sent again.
    for index in range(len(sent),len(chunks)):
        opening=[title] if is_forum and not sent else []
        sent.append(await post(token,sent[0] if is_forum and sent else channel_id,chunks[index],images if index==0 else [],f'rt-{report_id}-{index}',*opening))
        db.execute('UPDATE report_publications SET message_ids=? WHERE report_id=?',(json.dumps(sent),report_id))
    db.execute("UPDATE report_publications SET state='published',published_at=? WHERE report_id=?",(utcnow(),report_id))
    return sent,True,f'{sent[0]}/{sent[0]}' if is_forum else f'{channel_id}/{sent[0]}'
