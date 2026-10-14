"""Publish one approved report to Discord as RT Football Media, exactly once.

Posts over Discord's REST API with RT Media's own token, so the public post
carries the newsroom identity while approval stays with Coach.
"""
import asyncio
import json
import aiohttp
from .database import utcnow

API='https://discord.com/api/v10'
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


async def discord_post(token,channel_id,content,images,nonce):
    """Send one message. The enforced nonce makes Discord drop an accidental repeat."""
    payload={'content':content,'allowed_mentions':{'parse':[]},'nonce':nonce,'enforce_nonce':True,
             'attachments':[{'id':i,'filename':f'RT_Media_{i+1}.png'} for i in range(len(images))]}
    form=aiohttp.FormData();form.add_field('payload_json',json.dumps(payload),content_type='application/json')
    for i,data in enumerate(images):
        form.add_field(f'files[{i}]',data,filename=f'RT_Media_{i+1}.png',content_type='image/png')
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(f'{API}/channels/{channel_id}/messages',data=form,headers={'Authorization':'Bot '+token}) as response:
            if response.status>=300:
                raise PublishError(f'Discord refused the post (status {response.status}). Nothing further was sent.')
            return (await response.json())['id']


async def publish_report(db,report_id,token,channel_id,post=discord_post):
    """Returns (message_ids, newly_published). A report can only ever be published once."""
    # One publish at a time, so a double-tap cannot start two sends.
    async with LOCK:
        return await _publish(db,report_id,token,channel_id,post)


async def _publish(db,report_id,token,channel_id,post):
    if not token or not channel_id:
        raise PublishError('Publishing is not configured. Set RT_MEDIA_DISCORD_TOKEN and RT_MEDIA_PUBLISH_CHANNEL_ID.')
    report=db.report(report_id)
    if not report or report['status']!='approved':
        raise PublishError('Approve this draft before publishing.')
    saved=publication(db,report_id)
    if saved and saved['state']=='published':
        return json.loads(saved['message_ids']),False
    images,chunks=public_messages(db,report_id)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT OR IGNORE INTO report_publications(report_id,channel_id,state,claimed_at) VALUES (?,?,'publishing',?)",
                     (report_id,str(channel_id),utcnow()))
        row=conn.execute('SELECT * FROM report_publications WHERE report_id=?',(report_id,)).fetchone()
    if row['state']=='published':
        return json.loads(row['message_ids']),False
    if row['channel_id']!=str(channel_id):
        raise PublishError('This report was already started in another channel. Check that channel before retrying.')
    sent=json.loads(row['message_ids'])
    # Resume after an interrupted publish: messages already recorded are never sent again.
    for index in range(len(sent),len(chunks)):
        sent.append(await post(token,channel_id,chunks[index],images if index==0 else [],f'rt-{report_id}-{index}'))
        db.execute('UPDATE report_publications SET message_ids=? WHERE report_id=?',(json.dumps(sent),report_id))
    db.execute("UPDATE report_publications SET state='published',published_at=? WHERE report_id=?",(utcnow(),report_id))
    return sent,True
