"""Pep-owned match preparation: one persistent cup post, event and player RSVP."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import discord

log = logging.getLogger('gaffergpt')
CUP_ID = 'minglewood-2026-10-13-round-1'
KEY = 'cup_setup:' + CUP_ID
TITLE = 'Minglewood Cup R1 — Middlesbrough vs Birmingham City'
KICKOFF = datetime(2026, 10, 14, 2, tzinfo=timezone.utc)
POSTER = Path(__file__).parent / 'assets' / 'minglewood-cup-round1.jpg'

def norm(value):
    return re.sub(r'[^a-z0-9]+', '-', str(value).lower()).strip('-')

def load(db):
    return json.loads(db.setting(KEY) or '{}')

def persist(db, record):
    record['availability'] = load(db).get('availability', record.get('availability', {}))
    db.set_setting(KEY, json.dumps(record))

def unique(items, label):
    if len(items) != 1:
        raise ValueError(f'{label}: expected one match, found {len(items)}. Candidates: ' + ', '.join(f'{x.name} ({x.id})' for x in items))
    return items[0]

def body(record):
    votes = list(record.get('availability', {}).values())
    def group(status):
        names = [re.sub(r'[@*_`~<>\r\n]', '', v['name']) for v in votes if v['status'] == status]
        return f"{len(names)} — " + (', '.join(names) or 'None yet')
    return ("🏆 **MINGLEWOOD CUP — ROUND 1**\n**Middlesbrough vs Birmingham City — Away**\n"
            "**Single elimination**\n\n📅 Tuesday, October 13, 2026\n⚽ **Kickoff: 10:00 PM ET**\n"
            "🎮 **Be online by 8:00 PM ET**\n🚨 **ABSOLUTELY NO LATER THAN 8:30 PM ET**\n\n"
            "**MARK YOUR AVAILABILITY**\nEveryone needs to select **YES or NO** below ASAP so Coach can prep the lineup early. "
            "Your latest selection replaces your previous response. Tell management here if you will be late or need to leave early.\n\n"
            f"✅ YES: {group('yes')}\n❌ NO: {group('no')}\n\n**LINEUP**\n"
            "Coach will post the confirmed lineup in this thread once availability is collected.\n\n"
            f"📺 **Watch live:** <#{record['live_channel_id']}>\nLive stream and match updates will be in Live Games.\n\n"
            "**Pep • Birmingham Tactical Coach 🔵 | Keep Right On**")

def save_availability(db, user_id, name, role_ids, status, guild_id, channel_id, *, now=None):
    record = load(db)
    if not record or status not in ('yes', 'no') or guild_id != record['guild_id'] or channel_id != record.get('forum_post_id'):
        raise ValueError('This cup availability request is not active.')
    if record['player_role_id'] not in role_ids:
        raise ValueError('Only Birmingham City players can mark cup availability.')
    if (now or datetime.now(timezone.utc)) >= KICKOFF:
        raise ValueError('Cup availability is closed because kickoff has passed.')
    record.setdefault('availability', {})[str(user_id)] = {'status': status, 'name': name}
    db.set_setting(KEY, json.dumps(record))
    return record

class CupAvailabilityView(discord.ui.View):
    def __init__(self, db, lock=None):
        super().__init__(timeout=None)
        self.db = db
        self.lock = lock or asyncio.Lock()
        for status, label, emoji, style in [('yes', 'YES — Available', '✅', discord.ButtonStyle.success),
                                            ('no', 'NO — Unavailable', '❌', discord.ButtonStyle.danger)]:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f'pep_cup:{CUP_ID}:{status}')
            async def callback(interaction, selected=status):
                await self.respond(interaction, selected)
            button.callback = callback
            self.add_item(button)

    async def respond(self, interaction, status):
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.lock:
                record = save_availability(self.db, interaction.user.id, interaction.user.display_name,
                    [r.id for r in getattr(interaction.user, 'roles', [])], status, interaction.guild_id, interaction.channel_id)
                await interaction.message.edit(content=body(record), view=self, allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send(f'Your cup availability is now **{status.upper()}**.', ephemeral=True)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except Exception:
            log.exception('Pep cup availability update failed')
            await interaction.followup.send('Your response may be saved, but the post could not refresh. Tell Coach or try again.', ephemeral=True)

async def setup_cup(guild, db, *, now=None, poster_path=POSTER, lock=None):
    record = load(db)
    if record.get('status') == 'complete':
        return record
    if (now or datetime.now(timezone.utc)) >= KICKOFF:
        raise ValueError('Cup kickoff has passed; automatic setup is disabled.')
    poster_path = Path(poster_path)
    if not poster_path.is_file():
        raise ValueError('Cup poster is missing. Nothing was posted.')
    channels = await guild.fetch_channels()
    roles = await guild.fetch_roles()
    role = unique([r for r in roles if norm(r.name) == 'birmingham-city-players'], 'Birmingham City players role')
    live = unique([c for c in channels if norm(c.name) == 'live-games'], 'Live Games channel')
    forums = [c for c in channels if norm(c.name) in ('mpl-match-center', 'ml1-match-center') and hasattr(c, 'create_thread')]
    if len(forums) > 1:
        forums = [c for c in forums if 'birmingham' in norm(getattr(getattr(c, 'category', None), 'name', ''))]
    forum = unique(forums, 'Birmingham Match Center forum')
    me = guild.me
    if not me.guild_permissions.create_events:
        raise ValueError('Pep needs Create Events permission. No cup post was created.')
    permissions = forum.permissions_for(me)
    if not all(getattr(permissions, p) for p in ('view_channel', 'send_messages', 'send_messages_in_threads', 'read_message_history', 'attach_files')):
        raise ValueError('Pep needs forum view, post, thread reply, message history and attachment permissions.')
    if not role.mentionable and not permissions.mention_everyone:
        raise ValueError('Pep needs permission to mention the Birmingham City players role in the forum.')
    record.update(id=CUP_ID, guild_id=guild.id, player_role_id=role.id, live_channel_id=live.id,
                  forum_channel_id=forum.id, status='setting-up')
    persist(db, record)
    lock = lock or asyncio.Lock()
    view = CupAvailabilityView(db, lock)
    thread = None
    if record.get('forum_post_id'):
        try: thread = await guild.fetch_channel(record['forum_post_id'])
        except discord.NotFound: pass
    if thread is None:
        active = await guild.active_threads() if hasattr(guild, 'active_threads') else forum.threads
        archived = [t async for t in forum.archived_threads(limit=100)]
        matches = {t.id: t for t in [*active, *archived] if t.name == TITLE and getattr(t, 'parent_id', forum.id) == forum.id}
        if len(matches) > 1: raise ValueError('Multiple matching cup posts exist. No additional post was created.')
        thread = next(iter(matches.values()), None)
        if thread and thread.owner_id != me.id:
            raise ValueError('The cup post already exists from another author. Review it before Pep creates another.')
        if thread is None:
            result = await forum.create_thread(name=TITLE, content=body(record), view=view,
                file=discord.File(poster_path, filename='minglewood-cup-round1.jpg'),
                applied_tags=[t for t in forum.available_tags if t.name in ('Upcoming', 'Away', 'Cup')],
                allowed_mentions=discord.AllowedMentions.none(), reason='Coach-requested Minglewood Cup preparation')
            thread = result.thread
            record['starter_message_id'] = result.message.id
        record['forum_post_id'] = thread.id
        record.setdefault('starter_message_id', thread.id)
        persist(db, record)
    events = await guild.fetch_scheduled_events()
    event = next((e for e in events if e.id == record.get('event_id')), None)
    if event is None:
        matches = [e for e in events if e.name == TITLE and e.start_time == KICKOFF]
        if len(matches) > 1: raise ValueError('Multiple matching cup events exist.')
        event = matches[0] if matches else await guild.create_scheduled_event(name=TITLE,
            description=('Minglewood Cup — Round 1, single elimination. Away at Middlesbrough.\n'
                'Kickoff: 10:00 PM ET. Be online by 8:00 PM ET; absolutely NO LATER than 8:30 PM ET.\n'
                'Mark YES or NO in the forum ASAP so Coach can prepare the lineup early.\n'
                f'Cup forum: https://discord.com/channels/{guild.id}/{thread.id}\n'
                f'Live Games: https://discord.com/channels/{guild.id}/{live.id}\nPep • Birmingham Tactical Coach | Keep Right On'),
            start_time=KICKOFF, end_time=datetime(2026,10,14,3,30,tzinfo=timezone.utc),
            entity_type=discord.EntityType.external, privacy_level=discord.PrivacyLevel.guild_only,
            location='EA FC Pro Clubs — away at Middlesbrough', image=poster_path.read_bytes(),
            reason='Coach-requested cup event')
        record['event_id'] = event.id
        persist(db, record)
    if thread.archived: await thread.edit(archived=False)
    async with lock:
        persist(db, record)
        message = await thread.fetch_message(record['starter_message_id'])
        await message.edit(content=body(record), view=view, allowed_mentions=discord.AllowedMentions.none())
    if not record.get('ping_message_id'):
        content = (f'<@&{role.id}>\n**MINGLEWOOD CUP — AVAILABILITY**\n'
            'Cup tonight away at Middlesbrough, **10:00 PM ET kickoff — single elimination**. '
            'Everyone needs to mark **YES or NO** on the buttons above ASAP so Coach can prep the lineup early.\n\n'
            'Be on by **8:00 PM ET**, absolutely **NO LATER than 8:30 PM ET**. '
            f'If anything changes, let management know.\n\n📺 Live feed: <#{live.id}>\n'
            'Pep • Birmingham Tactical Coach 🔵 | Keep Right On')
        existing = await anext((m async for m in thread.history(limit=50) if m.content == content and m.author.id == me.id), None)
        ping = existing or await thread.send(content=content,
            allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False))
        record['ping_message_id'] = ping.id
        persist(db, record)
    record['status'] = 'complete'
    persist(db, record)
    return record

async def run_cup_setup(bot):
    await run_cup_gameplan(bot)
    cleanup_request=os.getenv('PEP_CUP_CLEANUP_REQUEST')
    cleanup_key='cup_cleanup:'+CUP_ID+':remove-link-previews-v1'
    if cleanup_request==CUP_ID and not bot.db.setting(cleanup_key):
        try:
            record=load(bot.db)
            channel=await bot.fetch_channel(record['forum_post_id'])
            async with bot.cup_availability_lock:
                message=await channel.fetch_message(record['starter_message_id'])
                await message.edit(content=body(load(bot.db)),view=CupAvailabilityView(bot.db,bot.cup_availability_lock),
                    embeds=[],suppress=True,allowed_mentions=discord.AllowedMentions.none())
                verified=await channel.fetch_message(record['starter_message_id'])
                if verified.embeds or 'https://discord.com/' in verified.content:
                    raise ValueError('Discord link previews are still present after the edit.')
                if not verified.attachments or not verified.components:
                    raise ValueError('Poster or availability buttons are missing after the edit.')
                bot.db.set_setting(cleanup_key,'complete')
                log.info('PEP_CUP_CLEANUP_RESULT %s',json.dumps(dict(status='complete',message_id=verified.id,
                    embed_count=len(verified.embeds),poster_count=len(verified.attachments),button_rows=len(verified.components))))
        except Exception as error:
            log.exception('PEP_CUP_CLEANUP_FAILED: %s',str(error))
    if os.getenv('PEP_CUP_SETUP_REQUEST') != CUP_ID or getattr(bot, 'cup_setup_running', False): return
    bot.cup_setup_running = True
    try:
        guild = bot.get_guild(bot.config.guild_id) or await bot.fetch_guild(bot.config.guild_id)
        record = await setup_cup(guild, bot.db, lock=bot.cup_availability_lock)
        log.info('PEP_CUP_SETUP_RESULT %s', json.dumps(dict(status=record['status'],
            forum_post_url=f"https://discord.com/channels/{record['guild_id']}/{record['forum_post_id']}",
            event_url=f"https://discord.com/events/{record['guild_id']}/{record['event_id']}",
            live_games_url=f"https://discord.com/channels/{record['guild_id']}/{record['live_channel_id']}",
            role_id=record['player_role_id'],ping_message_id=record['ping_message_id'])))
    except Exception as error:
        log.exception('PEP_CUP_SETUP_FAILED: %s', str(error))
    finally: bot.cup_setup_running = False

async def run_cup_gameplan(bot):
    """Coach-authorized one-time rundown and role ping in the existing cup thread."""
    if os.getenv('PEP_CUP_GAMEPLAN_REQUEST') != CUP_ID:
        return
    action_key = 'cup_gameplan:' + CUP_ID + ':v1'
    try:
        async with bot.cup_availability_lock:
            record = load(bot.db)
            expected_guild = 1524828767426707587
            expected_thread = 1559595763015876752
            expected_role = 1549476136893812866
            if (record.get('guild_id'), record.get('forum_post_id'), record.get('player_role_id')) != (expected_guild, expected_thread, expected_role):
                raise ValueError('Cup destination does not match the approved Birmingham thread and role.')
            thread = await bot.fetch_channel(expected_thread)
            if thread.id != expected_thread or thread.guild.id != expected_guild or thread.name != TITLE:
                raise ValueError('Fetched thread does not match the approved cup destination.')
            if thread.archived:
                await thread.edit(archived=False)
            footer = '\n\nPep • Birmingham Tactical Coach 🔵 | Keep Right On'
            messages = ['<@&1549476136893812866>\n**TONIGHT’S GAME PLAN — MIDDLESBROUGH**\n\nBoys, here’s the rundown for Middlesbrough tonight. They’re unbeaten in their last four, so don’t underestimate them. Their key guys from the recent stats:\n\n• **ThorfinnKenobi:** 4 assists in 7 games. Close his forward passing lanes and don’t give him time to pick a pass.\n• **JohnD151049:** leading scorer with 4 goals. Track his runs and the return ball. Don’t let him pull both CBs out.\n• **AGU1J7 and Idias4977:** both contributed in their recent wins. Watch their runs into the box while we’re focused on JohnD.\n• **eduardo1200rs:** plays GK or midfield, so confirm where he starts. If he’s in goal, he recorded 16 saves in their last four. Get wide and look for a teammate in the box. Make the keeper change position before we shoot.\n\n**OUR PLAN — 4-2-3-1**\n\nGive each other passing options, use quick give-and-go passes, and switch sides when it gets crowded. Their recent tackle success was low, so look to pass around defenders when they commit.\n\nBuild through the CBs and midfield. If the forward pass isn’t there, recycle it—don’t force it. Only one fullback pushes at a time, with midfield protecting the middle.\n\nPress together, stay on your feet, and track runners. Their stats came from partial squads, so we’ll adjust to the lineup they bring tonight.\n\nStay patient, communicate, and make our chances count. Keep Right On.\n\nPep • Birmingham Tactical Coach 🔵 | Keep Right On']
            state = json.loads(bot.db.setting(action_key) or '{}')
            ids = state.setdefault('message_ids', {})
            # Recover a send accepted by Discord before the local receipt was saved.
            history = [m async for m in thread.history(limit=200)]
            for index, content in enumerate(messages):
                key = str(index)
                if key in ids:
                    message = await thread.fetch_message(ids[key])
                else:
                    message = next((m for m in history if m.author.id == bot.user.id and m.content == content), None)
                    if message is None:
                        allowed = (discord.AllowedMentions(roles=[discord.Object(id=expected_role)], users=False, everyone=False, replied_user=False)
                                   if index == 0 else discord.AllowedMentions.none())
                        message = await thread.send(content=content, allowed_mentions=allowed)
                    ids[key] = message.id
                    bot.db.set_setting(action_key, json.dumps(state))
                verified = await thread.fetch_message(message.id)
                if verified.author.id != bot.user.id or verified.content != content:
                    raise ValueError('Posted game plan verification failed; no further messages were sent.')
            state['status'] = 'complete'
            bot.db.set_setting(action_key, json.dumps(state))
            log.info('PEP_CUP_GAMEPLAN_RESULT %s', json.dumps(dict(status='complete', thread_id=thread.id,
                message_ids=[ids[str(i)] for i in range(len(messages))], player_role_id=expected_role,
                forum_post_url=f'https://discord.com/channels/{expected_guild}/{thread.id}')))
    except Exception as error:
        log.exception('PEP_CUP_GAMEPLAN_FAILED: %s', str(error))
