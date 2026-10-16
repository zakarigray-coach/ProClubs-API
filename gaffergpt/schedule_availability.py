"""Persistent, separate fixture availability on the nine MPL match-night posts."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
import discord
from .schedule_once import GUILD_ID, FORUM_ID, RECEIPT_FILE, make_posts

log = logging.getLogger('gaffergpt')
PLAYER_ROLE_ID = 1549476136893812866
STAGE_ID = 1551687430170738828
STORE_FILE = 'mpl-season4-v2-availability.json'
STATUSES = (
    ('yes', 'Available', '✅', discord.ButtonStyle.success),
    ('maybe', 'Maybe', '❔', discord.ButtonStyle.secondary),
    ('no', 'Unavailable', '❌', discord.ButtonStyle.danger),
)


class AvailabilityStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def write(self, state):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state))
        temporary.replace(self.path)

    def responses(self, day):
        return self.load().get('votes', {}).get(day, {})

    def vote(self, day, user_id, name, roles, status, guild_id, thread_id, expected_thread, *, fixture=1, now=None):
        if guild_id != GUILD_ID or thread_id != expected_thread:
            raise ValueError('Use the buttons on the original match-night post.')
        if PLAYER_ROLE_ID not in roles:
            raise ValueError('Only Birmingham City players can mark availability.')
        if day not in {p['key'] for p in make_posts()} or status not in ('yes', 'maybe', 'no') or fixture not in (1, 2):
            raise ValueError('Invalid fixture or response.')
        kickoff = datetime.combine(datetime.fromisoformat(day).date(), time(22, 0 if fixture == 1 else 30), ZoneInfo('America/New_York'))
        if (now or datetime.now(ZoneInfo('America/New_York'))) >= kickoff:
            raise ValueError('Availability is closed for this fixture because kickoff has passed.')
        state = self.load()
        votes = state.setdefault('votes', {}).setdefault(day, {}).setdefault(str(fixture), {})
        votes[str(user_id)] = {'status': status, 'name': str(name)[:24]}
        self.write(state)
        return state['votes'][day]


def render(post, votes):
    lines = [post['content'], '', '**AVAILABILITY — RESPOND FOR EACH MATCH**',
             'Choose separately for each kickoff. Your latest choice replaces your previous response.',
             'Availability helps management select the squad; it does not guarantee a starting place.']
    for fixture, label in ((1, '10:00 PM — HOME'), (2, '10:30 PM — AWAY')):
        lines.extend(('', f'**{label}**'))
        responses = votes.get(str(fixture), {})
        for status, name, emoji, _ in STATUSES:
            names = [re.sub(r'[@*_`~<>\r\n|]', '', v['name']) for v in responses.values() if v['status'] == status]
            lines.append(f"{emoji} {name}: {len(names)} — " + (', '.join(names) or 'None yet'))
    content = '\n'.join(lines)
    # Keep the main message within Discord's limit even if the role grows.
    if len(content) > 1950:
        lines = [post['content'], '', '**AVAILABILITY — RESPOND FOR EACH MATCH**']
        for fixture, label in ((1, '10:00 PM — HOME'), (2, '10:30 PM — AWAY')):
            lines.extend(('', f'**{label}**'))
            for status, name, emoji, _ in STATUSES:
                count = sum(v['status'] == status for v in votes.get(str(fixture), {}).values())
                lines.append(f'{emoji} {name}: {count}')
        lines.append('Full player lists are attached. Update your choice if plans change.')
        content = '\n'.join(lines)
    return content


def roster_files(post, votes):
    """Attach complete named responses only when they cannot fit in the post."""
    import io
    if 'Full player lists are attached.' not in render(post, votes):
        return []
    lines = []
    for fixture in (1, 2):
        lines.append('10:00 PM HOME' if fixture == 1 else '10:30 PM AWAY')
        for status, name, _, _ in STATUSES:
            names = [v['name'] for v in votes.get(str(fixture), {}).values() if v['status'] == status]
            lines.append(f"{name} ({len(names)}): " + (', '.join(names) or 'None yet'))
    return [discord.File(io.BytesIO('\n'.join(lines).encode()), filename='availability.txt')]


class ScheduleAvailabilityView(discord.ui.View):
    def __init__(self, store, post, thread_id, lock):
        super().__init__(timeout=None)
        self.store = store
        self.post = post
        self.thread_id = thread_id
        self.lock = lock
        for fixture in (1, 2):
            kickoff = '10:00' if fixture == 1 else '10:30'
            for status, label, emoji, style in STATUSES:
                button = discord.ui.Button(label=f'{kickoff} • {label}', emoji=emoji, style=style,
                    row=fixture - 1, custom_id=f"cc_mpl:v2:{post['key']}:{fixture}:{status}")
                async def callback(interaction, selected=status, game=fixture):
                    await self.respond(interaction, selected, game)
                button.callback = callback
                self.add_item(button)

    async def respond(self, interaction, status, fixture):
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.message.id != self.thread_id:
                raise ValueError('Use the buttons on the original match-night post.')
            async with self.lock:
                votes = self.store.vote(self.post['key'], interaction.user.id, interaction.user.display_name,
                    [r.id for r in getattr(interaction.user, 'roles', [])], status,
                    interaction.guild_id, interaction.channel_id, self.thread_id, fixture=fixture)
                await interaction.message.edit(content=render(self.post, votes), view=self,
                    attachments=roster_files(self.post, votes), allowed_mentions=discord.AllowedMentions.none())
            label = dict((s, name) for s, name, _, _ in STATUSES)[status]
            kickoff = '10:00 PM' if fixture == 1 else '10:30 PM'
            await interaction.followup.send(f'You are marked **{label}** for {kickoff} ET on {self.post["key"]}.', ephemeral=True)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except Exception:
            log.exception('MPL availability update failed')
            await interaction.followup.send('Your response may be saved, but the count could not refresh. Please tap again or tell management.', ephemeral=True)


def register_availability(bot):
    folder = Path(bot.config.database_path).parent
    bot.mpl_availability_store = AvailabilityStore(folder / STORE_FILE)
    bot.mpl_availability_lock = asyncio.Lock()
    receipts = folder / RECEIPT_FILE
    if not receipts.exists():
        return
    state = json.loads(receipts.read_text())
    if state.get('forum_id') != FORUM_ID:
        return
    for post in make_posts():
        if state.get(post['key']):
            tid = int(state[post['key']])
            bot.add_view(ScheduleAvailabilityView(bot.mpl_availability_store, post, tid, bot.mpl_availability_lock), message_id=tid)
    log.info('CC_AVAILABILITY_REGISTERED count=%s', sum(bool(state.get(p['key'])) for p in make_posts()))


async def install_availability(bot):
    if os.getenv('PEP_SCHEDULE_AVAILABILITY') != 'enable-v2' or getattr(bot, '_mpl_availability_installing', False):
        return
    bot._mpl_availability_installing = True
    try:
        if bot.config.guild_id != GUILD_ID:
            raise ValueError('Wrong guild')
        store = bot.mpl_availability_store
        guild = bot.get_guild(GUILD_ID)
        roles = await guild.fetch_roles()
        if not any(r.id == PLAYER_ROLE_ID and 'birmingham' in r.name.lower() for r in roles):
            raise ValueError('Birmingham player role did not verify')
        receipts = json.loads((Path(bot.config.database_path).parent / RECEIPT_FILE).read_text())
        if not receipts.get('complete') or receipts.get('forum_id') != FORUM_ID:
            raise ValueError('Schedule receipt missing or incomplete')
        posts = make_posts()
        targets = []
        for post in posts:
            tid = int(receipts[post['key']])
            thread = await bot.fetch_channel(tid)
            if thread.guild.id != GUILD_ID or thread.parent_id != FORUM_ID or thread.name != post['title']:
                raise ValueError('Schedule destination changed')
            message = await thread.fetch_message(tid)
            if message.author.id != bot.user.id or not (message.content == post['content'] or message.content.startswith(post['content'] + '\n\n**AVAILABILITY')):
                raise ValueError('Existing schedule text or author changed')
            targets.append((post, thread, message))
        if store.path.exists():
            backup = store.path.with_suffix('.before-buttons.json')
            if not backup.exists():
                backup.write_bytes(store.path.read_bytes())
        stage = await bot.fetch_channel(STAGE_ID)
        if stage.guild.id != GUILD_ID or stage.permissions_for(guild.default_role).view_channel:
            raise ValueError('Staging channel is not private')
        post = posts[-1]
        preview = ScheduleAvailabilityView(store, post, 0, bot.mpl_availability_lock)
        for button in preview.children:
            button.disabled = True
        preview_text = '**PRIVATE TEST — SEPARATE FIXTURE AVAILABILITY V2**\n' + render(post, {})
        previous = await anext((m async for m in stage.history(limit=50) if m.author.id == bot.user.id and m.content == preview_text), None)
        test = previous or await stage.send(preview_text, view=preview, allowed_mentions=discord.AllowedMentions.none())
        test = await stage.fetch_message(test.id)
        if test.content != preview_text or sum(len(r.children) for r in test.components) != 6:
            raise ValueError('Private button rendering failed')
        log.info('CC_AVAILABILITY_STAGED buttons=6')
        for post, thread, message in targets:
            async with bot.mpl_availability_lock:
                if thread.archived:
                    await thread.edit(archived=False)
                view = ScheduleAvailabilityView(store, post, thread.id, bot.mpl_availability_lock)
                votes = store.responses(post['key'])
                content = render(post, votes)
                await message.edit(content=content, view=view, attachments=roster_files(post, votes), allowed_mentions=discord.AllowedMentions.none())
                verified = await thread.fetch_message(message.id)
                actual = [b.custom_id for row in verified.components for b in row.children]
                if verified.content != content or actual != [b.custom_id for b in view.children]:
                    raise ValueError('Public availability buttons failed verification')
                bot.add_view(view, message_id=thread.id)
            log.info('CC_AVAILABILITY_POST date=%s thread=%s buttons=6', post['key'], thread.id)
        async with bot.mpl_availability_lock:
            state = store.load()
            state['installed'] = True
            store.write(state)
        log.info('CC_AVAILABILITY_COMPLETE count=9')
    except Exception:
        log.exception('CC_AVAILABILITY_FAILED')
    finally:
        bot._mpl_availability_installing = False
