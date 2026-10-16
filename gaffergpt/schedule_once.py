"""Coach-authorized single MPL schedule import; no feed or recurring job."""
import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger('gaffergpt')
GUILD_ID = 1524828767426707587
ACTION = 'mpl-season4-2026-v1'

def make_posts():
    rows = json.loads(Path(__file__).with_name('mpl_schedule_2026.json').read_text())
    if len(rows) != 18 or len({m['id'] for m in rows}) != 18:
        raise ValueError('Expected 18 unique verified fixtures')
    days = defaultdict(list)
    for m in rows:
        date = datetime.fromtimestamp(m['timestamp'], ZoneInfo('America/New_York')).date()
        days[date].append(m)
    posts = []
    for day, matches in sorted(days.items(), reverse=True):
        matches.sort(key=lambda m: m['timestamp'])
        if len(matches) != 2: raise ValueError('Expected two fixtures per match night')
        opponent = next(m['away'] if m['home'] == 'MPL BirminghamCity' else m['home'] for m in matches).removeprefix('MPL ')
        content = f'🔵 **BIRMINGHAM CITY — MPL SEASON 4**\n📅 **{day:%A, %B %d, %Y}**\n\n'
        for i, m in enumerate(matches):
            home = m['home'].removeprefix('MPL ').replace('BirminghamCity', 'Birmingham City')
            away = m['away'].removeprefix('MPL ').replace('BirminghamCity', 'Birmingham City')
            venue = 'HOME' if m['home'] == 'MPL BirminghamCity' else 'AWAY'
            content += f"**10:{'00' if i == 0 else '30'} PM ET — {venue}**\n{home} vs {away}\n{m['round']} • [Official fixture](<{m['url']}>)\n\n"
        content += 'All kickoff times are Eastern Time, confirmed by Coach.\n**Keep Right On 🔵**'
        posts.append(dict(key=day.isoformat(),title=f'{day:%b %d} | Birmingham City vs {opponent} | 10 & 10:30 PM ET',content=content))
    return posts

async def publish_posts(forum, posts, author_id, existing, save):
    """Recover accepted sends by exact title/body before making another post."""
    import discord
    for p in posts:
        matches = [t for t in existing if t.name == p['title']]
        if len(matches) > 1: raise ValueError('Duplicate existing schedule titles; review required')
        if matches:
            thread = matches[0]
            msg = await thread.fetch_message(thread.id)
            if msg.author.id != author_id or msg.content != p['content']:
                raise ValueError('Existing schedule post differs; refusing duplicate or overwrite')
        else:
            result = await forum.create_thread(name=p['title'], content=p['content'],
                allowed_mentions=discord.AllowedMentions.none(),
                applied_tags=[t for t in forum.available_tags if t.name.lower() in ('upcoming','league','mpl')],
                reason='Coach-authorized one-time MPL schedule')
            thread = result.thread
            existing.append(thread)
        msg = await thread.fetch_message(thread.id)
        if msg.content != p['content'] or msg.author.id != author_id:
            raise ValueError('Posted schedule did not verify')
        save(p['key'], thread.id)
        log.info('PEP_SCHEDULE_POST %s',json.dumps(dict(date=p['key'],url=f'https://discord.com/channels/{GUILD_ID}/{thread.id}')))

async def run_schedule_once(bot):
    mode = os.getenv('PEP_SCHEDULE_ONCE', '')
    if mode not in ('inspect', 'stage', ACTION) or getattr(bot, '_schedule_once_running', False): return
    bot._schedule_once_running = True
    try:
        import discord
        if bot.config.guild_id != GUILD_ID: raise ValueError('Wrong guild')
        guild = bot.get_guild(GUILD_ID)
        channels = await guild.fetch_channels()
        if mode == 'inspect':
            log.info('PEP_SCHEDULE_CHANNELS %s',json.dumps([dict(id=c.id,name=c.name,type=c.type.value,category=c.category_id) for c in channels]))
            return
        stage_id = int(os.environ['PEP_SCHEDULE_STAGE_ID'])
        stage = next(c for c in channels if c.id == stage_id)
        if not isinstance(stage, discord.TextChannel) or stage.permissions_for(guild.default_role).view_channel:
            raise ValueError('Staging must be a private text channel')
        posts = make_posts()
        path = Path(bot.config.database_path).parent / 'mpl-season4-once.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        def save(key,value):
            state[key] = value
            temp = path.with_suffix('.tmp'); temp.write_text(json.dumps(state)); temp.replace(path)
        if not state.get('staged'):
            history = [m async for m in stage.history(limit=100)]
            for p in posts:
                content = f"**SCHEDULE TEST — {p['title']}**\n\n{p['content']}"
                msg = next((m for m in history if m.author.id == bot.user.id and m.content == content),None)
                if msg is None: msg = await stage.send(content,allowed_mentions=discord.AllowedMentions.none())
                verified = await stage.fetch_message(msg.id)
                if verified.content != content: raise ValueError('Private staging verification failed')
            save('staged',True)
        log.info('PEP_SCHEDULE_STAGED count=%s',len(posts))
        if mode == 'stage': return
        forum_id = int(os.environ['PEP_SCHEDULE_FORUM_ID'])
        forum = next(c for c in channels if c.id == forum_id)
        if not isinstance(forum,discord.ForumChannel) or forum.id != 1552369533992304660 or 'mpl-match-center' not in forum.name.lower():
            raise ValueError('Destination must be the verified Birmingham MPL match-center forum')
        if state.get('forum_id') not in (None,forum_id): raise ValueError('Destination changed')
        if state.get('complete'):
            log.info('PEP_SCHEDULE_COMPLETE already-posted forum=%s',forum_id); return
        existing = [t for t in await guild.active_threads() if t.parent_id == forum_id]
        existing += [t async for t in forum.archived_threads(limit=None)]
        # Preflight every matching title before sending any new post.
        for p in posts:
            matches = [t for t in existing if t.name == p['title']]
            if len(matches)>1: raise ValueError('Duplicate schedule detected')
            if p['key'] in state and not any(t.id == state[p['key']] for t in matches):
                raise ValueError('Previously posted schedule missing; refusing to recreate')
            if matches:
                msg = await matches[0].fetch_message(matches[0].id)
                if msg.author.id != bot.user.id or msg.content != p['content']: raise ValueError('Conflicting existing post')
        save('forum_id',forum_id)
        await publish_posts(forum,posts,bot.user.id,existing,save)
        save('complete',True)
        log.info('PEP_SCHEDULE_COMPLETE %s',json.dumps(state))
    except Exception:
        log.exception('PEP_SCHEDULE_FAILED')
    finally:
        bot._schedule_once_running = False
