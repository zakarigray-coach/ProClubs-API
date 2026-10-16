"""Owner-requested calendar entries linked to the nine verified forum posts."""
import asyncio
import json
import logging
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from .schedule_once import GUILD_ID, FORUM_ID, RECEIPT_FILE, make_posts
from .schedule_availability import STAGE_ID

log = logging.getLogger('gaffergpt')
EVENT_RECEIPT = 'mpl-season4-v2-events.json'


def event_spec(post, thread_id):
    start = datetime.combine(datetime.fromisoformat(post['key']).date(), time(22), ZoneInfo('America/New_York')).astimezone(timezone.utc)
    forum_url = f'https://discord.com/channels/{GUILD_ID}/{thread_id}'
    return {'key': post['key'], 'forum_url': forum_url, 'kwargs': {
        'name': post['title'], 'start_time': start, 'end_time': start + timedelta(hours=1),
        'entity_type': discord.EntityType.external, 'privacy_level': discord.PrivacyLevel.guild_only,
        'location': forum_url,
        'description': ('Birmingham City — MPL match night.\n'
            '10:00 PM Eastern — HOME\n10:30 PM Eastern — AWAY\n'
            'Calendar block: 10–11 PM Eastern.\n'
            'Mark availability separately for each fixture using the forum buttons.\n'
            'Lineups, positions, late arrivals and match coordination stay in the linked thread.\n'
            f'Match-night forum: {forum_url}\nC&C Management | Keep Right On 🔵'),
        'reason': 'Coach requested match dates in server Events linked to the forum',
    }}


async def verify_event(guild, event, spec, author_id):
    if event.creator_id != author_id:
        raise ValueError('Calendar entry has a different author; refusing duplicate or overwrite')
    # discord.py 2.7.1 incorrectly derives ScheduledEvent.privacy_level
    # from status. Verify the actual API privacy field instead.
    raw = await guild._state.http.get_scheduled_event(guild.id, event.id, with_user_count=False)
    if raw.get('privacy_level') != spec['kwargs']['privacy_level'].value:
        raise ValueError('Calendar entry must be server-only')
    for field, expected in spec['kwargs'].items():
        if field not in ('reason', 'privacy_level') and getattr(event, field) != expected:
            raise ValueError(f'Calendar entry differs: {spec["key"]} {field}')


async def publish_events(guild, specs, author_id, existing, receipts, save):
    targets = []
    # Validate every candidate before creating even the first event.
    for spec in specs:
        matches = [e for e in existing if e.name == spec['kwargs']['name']]
        if len(matches) > 1:
            raise ValueError('Duplicate calendar entries detected')
        event = matches[0] if matches else None
        saved = receipts.get(spec['key'], {}).get('event_id')
        if saved and (event is None or event.id != saved):
            raise ValueError('Previously created event is missing or changed; refusing to recreate')
        if event is not None:
            await verify_event(guild, event, spec, author_id)
        targets.append((spec, event))
    result = {}
    for spec, event in targets:
        if event is None:
            event = await guild.create_scheduled_event(**spec['kwargs'])
        verified = await guild.fetch_scheduled_event(event.id)
        await verify_event(guild, verified, spec, author_id)
        receipts.setdefault(spec['key'], {})['event_id'] = event.id
        save()
        result[spec['key']] = verified
        log.info('CC_EVENTS_POST date=%s url=https://discord.com/events/%s/%s forum=%s',
                 spec['key'], GUILD_ID, event.id, spec['forum_url'])
    return result


async def run_schedule_events(bot):
    if os.getenv('PEP_SCHEDULE_EVENTS') != 'enable-v2' or getattr(bot, '_cc_events_running', False):
        return
    bot._cc_events_running = True
    try:
        if bot.config.guild_id != GUILD_ID:
            raise ValueError('Wrong server')
        folder = Path(bot.config.database_path).parent
        forum_receipts = json.loads((folder / RECEIPT_FILE).read_text())
        if not forum_receipts.get('complete') or forum_receipts.get('forum_id') != FORUM_ID:
            raise ValueError('Verified forum schedule is required before creating Events')
        guild = bot.get_guild(GUILD_ID)
        specs, threads = [], {}
        for post in make_posts():
            tid = int(forum_receipts[post['key']])
            thread = await bot.fetch_channel(tid)
            if thread.guild.id != GUILD_ID or thread.parent_id != FORUM_ID or thread.name != post['title']:
                raise ValueError('Forum destination changed')
            message = await thread.fetch_message(tid)
            if message.author.id != bot.user.id or not message.content.startswith(post['content'] + '\n\n**AVAILABILITY'):
                raise ValueError('Forum author or contents changed')
            if sum(len(row.children) for row in message.components) != 6:
                raise ValueError('Both fixture availability rows must be installed first')
            specs.append(event_spec(post, tid))
            threads[post['key']] = thread
        existing = await guild.fetch_scheduled_events()
        path = folder / EVENT_RECEIPT
        state = json.loads(path.read_text()) if path.exists() else {'events': {}}
        def save():
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state))
            temporary.replace(path)
        if not state.get('staged'):
            stage = await bot.fetch_channel(STAGE_ID)
            if stage.guild.id != GUILD_ID or stage.permissions_for(guild.default_role).view_channel:
                raise ValueError('Calendar staging channel is not private')
            text = '**PRIVATE TEST — LINKED MATCH-NIGHT EVENTS**\n' + '\n\n'.join(
                f"{s['key']} | 10–11 PM Eastern\n{s['forum_url']}" for s in specs)
            previous = await anext((m async for m in stage.history(limit=50) if m.author.id == bot.user.id and m.content == text), None)
            preview = previous or await stage.send(text, allowed_mentions=discord.AllowedMentions.none())
            if (await stage.fetch_message(preview.id)).content != text:
                raise ValueError('Private calendar preview did not verify')
            from .notebook import daily_backup
            await asyncio.to_thread(daily_backup, bot.db, refresh=True)
            state['staged'] = True
            save()
            log.info('CC_EVENTS_STAGED count=9')
        events = await publish_events(guild, specs, bot.user.id, existing, state['events'], save)
        for spec in specs:
            day = spec['key']
            event = events[day]
            thread = threads[day]
            event_url = f'https://discord.com/events/{GUILD_ID}/{event.id}'
            content = ('📅 **MATCH-NIGHT EVENT**\n' + event_url + '\n'
                'This date is saved in server Events. Kickoffs: **10:00 PM Home / 10:30 PM Away, Eastern**.\n'
                'Use the buttons on the opening post to mark availability for each fixture.')
            record = state['events'][day]
            if record.get('link_message_id'):
                message = await thread.fetch_message(record['link_message_id'])
                if message.author.id != bot.user.id or message.content != content:
                    raise ValueError('Existing forum Event link changed')
            else:
                message = await anext((m async for m in thread.history(limit=100) if m.author.id == bot.user.id and m.content == content), None)
                if message is None:
                    if thread.archived:
                        await thread.edit(archived=False)
                    message = await thread.send(content, allowed_mentions=discord.AllowedMentions.none())
                verified = await thread.fetch_message(message.id)
                if verified.content != content or verified.author.id != bot.user.id:
                    raise ValueError('Forum Event link did not verify')
                record['link_message_id'] = message.id
                save()
            log.info('CC_EVENTS_LINKED date=%s thread=%s event=%s', day, thread.id, event.id)
        state['complete'] = True
        save()
        log.info('CC_EVENTS_COMPLETE count=9')
    except Exception:
        log.exception('CC_EVENTS_FAILED')
    finally:
        bot._cc_events_running = False
