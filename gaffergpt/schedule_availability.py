"""Persistent player RSVP buttons on the existing nine MPL match-night posts."""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
import discord
from .schedule_once import GUILD_ID, make_posts

log = logging.getLogger('gaffergpt')
PLAYER_ROLE_ID = 1549476136893812866
FORUM_ID = 1552369533992304660
STAGE_ID = 1551687430170738828

class AvailabilityStore:
    def __init__(self,path): self.path=Path(path)
    def load(self): return json.loads(self.path.read_text()) if self.path.exists() else {}
    def write(self,state):
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state));temporary.replace(self.path)
    def responses(self,day): return self.load().get('votes',{}).get(day,{})
    def vote(self,day,user_id,name,roles,status,guild_id,thread_id,expected_thread,*,now=None):
        if guild_id!=GUILD_ID or thread_id!=expected_thread:
            raise ValueError('Use the buttons on the original match-night post.')
        if PLAYER_ROLE_ID not in roles:
            raise ValueError('Only Birmingham City players can mark availability.')
        if day not in {p['key'] for p in make_posts()} or status not in ('yes','no'):
            raise ValueError('Invalid match night or response.')
        kickoff=datetime.combine(datetime.fromisoformat(day).date(),time(22),ZoneInfo('America/New_York'))
        if (now or datetime.now(ZoneInfo('America/New_York'))) >= kickoff:
            raise ValueError('Availability is closed because the first kickoff has passed.')
        state=self.load()
        votes=state.setdefault('votes',{}).setdefault(day,{})
        votes[str(user_id)]={'status':status,'name':str(name)[:32]}
        self.write(state)
        return votes

def render(post,votes):
    def group(status):
        names=[re.sub(r'[@*_`~<>\r\n|]', '',v['name']) for v in votes.values() if v['status']==status]
        return f"{len(names)} — "+(', '.join(names) or 'None yet')
    return (post['content']+'\n\n**MARK YOUR AVAILABILITY — BOTH GAMES**\n'
        'Choose YES or NO below. Your latest response replaces your previous one. '
        'If you can play only one game or will be late, tell management in this thread.\n\n'
        f"✅ YES: {group('yes')}\n❌ NO: {group('no')}")

class ScheduleAvailabilityView(discord.ui.View):
    def __init__(self,store,post,thread_id,lock):
        super().__init__(timeout=None)
        self.store=store;self.post=post;self.thread_id=thread_id;self.lock=lock
        for status,label,emoji,style in [('yes','YES — Available','✅',discord.ButtonStyle.success),('no','NO — Unavailable','❌',discord.ButtonStyle.danger)]:
            button=discord.ui.Button(label=label,emoji=emoji,style=style,custom_id=f"pep_mpl:{post['key']}:{status}")
            async def callback(interaction,selected=status): await self.respond(interaction,selected)
            button.callback=callback;self.add_item(button)
    async def respond(self,interaction,status):
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.message.id!=self.thread_id:
                raise ValueError('Use the buttons on the original match-night post.')
            async with self.lock:
                votes=self.store.vote(self.post['key'],interaction.user.id,interaction.user.display_name,
                    [r.id for r in getattr(interaction.user,'roles',[])],status,interaction.guild_id,interaction.channel_id,self.thread_id)
                await interaction.message.edit(content=render(self.post,votes),view=self,allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send(f"You are marked **{status.upper()}** for both games on {self.post['key']}.",ephemeral=True)
        except ValueError as error:
            await interaction.followup.send(str(error),ephemeral=True)
        except Exception:
            log.exception('MPL availability update failed')
            await interaction.followup.send('Your response may be saved, but the count could not refresh. Please tap again or tell Coach.',ephemeral=True)

def register_availability(bot):
    folder=Path(bot.config.database_path).parent
    bot.mpl_availability_store=AvailabilityStore(folder/'mpl-season4-availability.json')
    bot.mpl_availability_lock=asyncio.Lock()
    receipts=folder/'mpl-season4-once.json'
    if not receipts.exists(): return
    state=json.loads(receipts.read_text())
    if state.get('forum_id')!=FORUM_ID: return
    for post in make_posts():
        if state.get(post['key']):
            tid=int(state[post['key']])
            bot.add_view(ScheduleAvailabilityView(bot.mpl_availability_store,post,tid,bot.mpl_availability_lock),message_id=tid)

async def install_availability(bot):
    if os.getenv('PEP_SCHEDULE_AVAILABILITY')!='enable-v1' or getattr(bot,'_mpl_availability_installing',False): return
    bot._mpl_availability_installing=True
    try:
        if bot.config.guild_id!=GUILD_ID: raise ValueError('Wrong guild')
        store=bot.mpl_availability_store
        if store.load().get('installed'):
            log.info('PEP_AVAILABILITY_COMPLETE already-installed');return
        guild=bot.get_guild(GUILD_ID)
        roles=await guild.fetch_roles()
        if not any(r.id==PLAYER_ROLE_ID and 'birmingham' in r.name.lower() for r in roles):
            raise ValueError('Birmingham player role did not verify')
        receipts=json.loads((Path(bot.config.database_path).parent/'mpl-season4-once.json').read_text())
        if not receipts.get('complete') or receipts.get('forum_id')!=FORUM_ID:
            raise ValueError('Schedule receipt missing or incomplete')
        posts=make_posts();targets=[]
        # Validate every destination before editing any public message.
        for post in posts:
            tid=int(receipts[post['key']]);thread=await bot.fetch_channel(tid)
            if thread.guild.id!=GUILD_ID or thread.parent_id!=FORUM_ID or thread.name!=post['title']:
                raise ValueError('Schedule destination changed')
            message=await thread.fetch_message(tid)
            if message.author.id!=bot.user.id or not (message.content==post['content'] or message.content.startswith(post['content']+'\n\n**MARK YOUR AVAILABILITY')):
                raise ValueError('Existing schedule text or author changed')
            targets.append((post,thread,message))
        # Preserve RSVP state before any migration; never touch the match database.
        if store.path.exists():
            backup=store.path.with_suffix('.before-buttons.json')
            if not backup.exists(): backup.write_bytes(store.path.read_bytes())
        stage=await bot.fetch_channel(STAGE_ID)
        if stage.guild.id!=GUILD_ID or stage.permissions_for(guild.default_role).view_channel:
            raise ValueError('Staging channel is not private')
        post=posts[-1]
        preview=ScheduleAvailabilityView(store,post,0,bot.mpl_availability_lock)
        for button in preview.children: button.disabled=True
        preview_text='**PRIVATE TEST — AVAILABILITY BUTTONS**\n'+render(post,{})
        previous=await anext((m async for m in stage.history(limit=50) if m.author.id==bot.user.id and m.content==preview_text),None)
        test=previous or await stage.send(preview_text,view=preview,allowed_mentions=discord.AllowedMentions.none())
        test=await stage.fetch_message(test.id)
        if test.content!=preview_text or sum(len(r.children) for r in test.components)!=2:
            raise ValueError('Private button rendering failed')
        log.info('PEP_AVAILABILITY_STAGED buttons=2')
        for post,thread,message in targets:
            async with bot.mpl_availability_lock:
                if thread.archived: await thread.edit(archived=False)
                view=ScheduleAvailabilityView(store,post,thread.id,bot.mpl_availability_lock)
                content=render(post,store.responses(post['key']))
                await message.edit(content=content,view=view,allowed_mentions=discord.AllowedMentions.none())
                verified=await thread.fetch_message(message.id)
                if verified.content!=content or sum(len(r.children) for r in verified.components)!=2:
                    raise ValueError('Public availability buttons failed verification')
            log.info('PEP_AVAILABILITY_POST date=%s thread=%s buttons=2',post['key'],thread.id)
        async with bot.mpl_availability_lock:
            state=store.load();state['installed']=True;store.write(state)
        log.info('PEP_AVAILABILITY_COMPLETE count=9')
    except Exception:
        log.exception('PEP_AVAILABILITY_FAILED')
    finally: bot._mpl_availability_installing=False
