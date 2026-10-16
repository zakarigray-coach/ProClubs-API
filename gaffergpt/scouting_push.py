"""Owner-authorized one-time opposition scouting post to the verified Man United MPL forum thread."""
import base64
import hashlib
import io
import json
import logging
import os
from pathlib import Path

import discord

log = logging.getLogger('gaffergpt')

GUILD_ID = 1524828767426707587
FORUM_ID = 1552369533992304660
THREAD_ID = 1560710202679107745
THREAD_TITLE = 'Oct 20 | Birmingham City vs Man Utd. | 10 & 10:30 PM ET'
ACTION = 'man-utd-opposition-brief-2026-10-20-v1'
RECEIPT_FILE = 'man-utd-opposition-brief-2026-10-20.json'
ATTACHMENT_NAME = 'Birmingham_vs_Man_United_Opposition_Brief.jpg'
ASSET_SHA256 = '3f36607a3f4801ca7221ec6980f0439f46cb98cc22b86b623ce7ff47eb6a78b0'
MARKER = 'C&C Management | Opposition Scout | Man United | 2026-10-20'
CONTENT = (
    '📋 **OPPOSITION SCOUT — MAN UNITED**\n'
    'MPL Season 4 • Tuesday, October 20 • 10:00 PM & 10:30 PM ET\n\n'
    '**Match focus:** Protect the middle. Deny dasbecks forward-facing receptions. '
    'Force United wide and attack the channels behind the fullbacks.\n\n'
    'Full match-preparation brief attached below.\n'
    f'**{MARKER}**'
)


def _state_path(bot):
    return Path(bot.config.database_path).parent / RECEIPT_FILE


def _load_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state))
    temp.replace(path)


def _asset_bytes():
    encoded = ''.join(os.getenv(f'PEP_SCOUT_IMAGE_{i}', '') for i in range(1, 8))
    if not encoded:
        raise ValueError('Opposition brief image variables are missing')
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != ASSET_SHA256:
        raise ValueError('Opposition brief asset checksum mismatch')
    return data


def _matches(message, bot_user_id):
    if message.author.id != bot_user_id or MARKER not in message.content:
        return False
    return any(a.filename == ATTACHMENT_NAME for a in message.attachments)


async def run_scouting_push(bot):
    if os.getenv('PEP_SCOUT_PUSH', '') != ACTION or getattr(bot, '_scout_push_running', False):
        return
    bot._scout_push_running = True
    try:
        if bot.config.guild_id != GUILD_ID:
            raise ValueError('Wrong guild; refusing scouting post')
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            raise ValueError('Configured guild unavailable')

        thread = await bot.fetch_channel(THREAD_ID)
        if not isinstance(thread, discord.Thread):
            raise ValueError('Scouting destination is not a Discord thread')
        if thread.guild.id != GUILD_ID or thread.parent_id != FORUM_ID or thread.name != THREAD_TITLE:
            raise ValueError('Scouting destination metadata mismatch')

        starter = await thread.fetch_message(thread.id)
        if starter.author.id != bot.user.id or 'BIRMINGHAM CITY — MPL SEASON 4' not in starter.content:
            raise ValueError('Forum starter message did not verify')

        state_path = _state_path(bot)
        state = _load_state(state_path)
        if state.get('message_id'):
            try:
                message = await thread.fetch_message(int(state['message_id']))
            except discord.NotFound:
                raise ValueError('Recorded scouting post is missing; refusing to recreate automatically')
            if not _matches(message, bot.user.id):
                raise ValueError('Recorded scouting post no longer matches expected content')
            log.info('PEP_SCOUT_PUSH_COMPLETE verified-existing thread=%s message=%s', THREAD_ID, message.id)
            return

        async for message in thread.history(limit=100):
            if _matches(message, bot.user.id):
                state.update({'thread_id': THREAD_ID, 'message_id': message.id, 'complete': True})
                _save_state(state_path, state)
                log.info('PEP_SCOUT_PUSH_COMPLETE recovered-existing thread=%s message=%s', THREAD_ID, message.id)
                return

        data = _asset_bytes()
        sent = await thread.send(
            CONTENT,
            file=discord.File(io.BytesIO(data), filename=ATTACHMENT_NAME),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        verified = await thread.fetch_message(sent.id)
        if not _matches(verified, bot.user.id):
            raise ValueError('Scouting post verification failed')

        state.update({'thread_id': THREAD_ID, 'message_id': verified.id, 'complete': True})
        _save_state(state_path, state)
        log.info(
            'PEP_SCOUT_PUSH_COMPLETE %s',
            json.dumps({'thread_id': THREAD_ID, 'message_id': verified.id, 'url': f'https://discord.com/channels/{GUILD_ID}/{THREAD_ID}/{verified.id}'})
        )
    except Exception:
        log.exception('PEP_SCOUT_PUSH_FAILED')
    finally:
        bot._scout_push_running = False
