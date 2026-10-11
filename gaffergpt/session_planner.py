"""Discord Session Planner, persistent RSVPs and linked Scheduled Events."""
import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime,timezone,timedelta
import discord
from discord import app_commands
from .database import utcnow
from .session_store import SessionStore,TYPES,RESPONSES,ET,local_time

log=logging.getLogger('gaffergpt.sessions')


def phase(session,now=None):
    if session['status']=='Cancelled':return 'Cancelled'
    now=now or utcnow()
    return 'Past' if session['end_at']<=now else 'In progress' if session['start_at']<=now else 'Upcoming'


def format_time(value,style):
    if not value:return 'No deadline set'
    dt=datetime.fromisoformat(value)
    if style=='discord':return f'<t:{int(dt.timestamp())}:F>'
    return dt.astimezone(ET).strftime('%A, %d %B %Y • %I:%M %p %Z' if style=='long' else '%m/%d/%Y • %I:%M %p %Z')


def render_embed(store,session):
    layout=store.template(session['template_id'])['layout'];rows=store.attendance(session['session_id'])
    title=layout['header'].replace('{title}',session['title']).replace('{club}',session['club']).replace('{type}',session['session_type'])
    if session['status']=='Cancelled':title='CANCELLED — '+title
    embed=discord.Embed(title=title[:256],colour=int(layout['colour'][1:],16))
    fields={'description':('Session Focus',session['description']),
            'time':('Date / Time',format_time(session['start_at'],layout['date_format'])+'\nEnds: '+format_time(session['end_at'],layout['date_format'])),
            'type':('Session Type',session['session_type']),'club':('Club / Team',session['club']),
            'location':('Location',f'<#{session["voice_channel_id"]}>' if session['voice_channel_id'] else session['location']),
            'required':('Attendance','Required' if session['required'] else 'Optional'),
            'deadline':('Respond By',format_time(session['deadline_at'] or session['start_at'],layout['date_format'])),
            'minimum':('Minimum Players',str(session['min_players']) if session['min_players'] else ''),
            'lineup':('⚠️ LINEUP CONSIDERATION',session['lineup_note']), 'notes':('Notes',session['notes'])}
    for custom in layout['custom_fields']:fields[custom['key']]=(custom['name'],custom['value'])
    for key in layout['order']:
        if key in layout['hidden']:continue
        if key=='attendance':
            for status in RESPONSES:
                group=[r for r in rows if r['status']==status]
                names=[];length=0
                for row in group:
                    name=discord.utils.escape_markdown(row['display_name'])
                    if length+len(name)+2>850:break
                    names.append(name);length+=len(name)+2
                text='\n'.join(names) or 'No responses yet'
                if len(names)<len(group):text+=f'\n+{len(group)-len(names)} more — open Session Planner for the full list.'
                embed.add_field(name=layout['buttons'][status]['emoji']+' '+status+f' — {len(group)}',value=text,inline=False)
        elif key=='description' and session['description']:
            # Position is controlled by the section order, including top or bottom.
            for i in range(0,len(session['description']),900):embed.add_field(name='Session Focus' if i==0 else 'Continued',value=session['description'][i:i+900],inline=False)
        elif key in fields and fields[key][1]:
            inline=next((f.get('inline',False) for f in layout['custom_fields'] if f['key']==key),False)
            embed.add_field(name=fields[key][0],value=fields[key][1][:1024],inline=inline)
    if layout['logo_url']:embed.set_thumbnail(url=layout['logo_url'])
    if layout['banner_url']:embed.set_image(url=layout['banner_url'])
    embed.set_footer(text=layout['footer']+f' | Session #{session["session_id"]}')
    # Discord limits total embed text to 6000; full attendance stays in the dashboard.
    if len(embed)>5900:
        for index,field in enumerate(embed.fields):
            if any(field.name.startswith(layout['buttons'][status]['emoji']+' '+status+' —') for status in RESPONSES):
                embed.set_field_at(index,name=field.name,value='Open Session Planner for the full player list.',inline=False)
    if len(embed)>5900:
        raise ValueError('The layout contains too much text for a Discord post. Hide sections or shorten custom fields.')
    return embed


class RSVPView(discord.ui.View):
    def __init__(self,service,sid):
        super().__init__(timeout=None);self.service=service;self.sid=sid
        session=service.store.get(sid);layout=service.store.template(session['template_id'])['layout']
        closed=session['status']=='Cancelled' or phase(session)=='Past' or utcnow()>=(session['deadline_at'] or session['start_at'])
        for status,style in zip(RESPONSES,(discord.ButtonStyle.success,discord.ButtonStyle.secondary,discord.ButtonStyle.danger)):
            settings=layout['buttons'][status]
            button=discord.ui.Button(label=settings['label'],emoji=settings['emoji'] or None,style=style,custom_id=f'pep:rsvp:{sid}:{status}',disabled=closed)
            async def respond(interaction,value=status):
                if interaction.guild_id!=service.bot.config.guild_id or interaction.user.bot:
                    await interaction.response.send_message('Use this session in the club server.',ephemeral=True);return
                await interaction.response.defer(ephemeral=True)
                try:
                    await service.respond(sid,interaction.user,value,interaction.user.id)
                    await interaction.followup.send('Saved: '+value+'.',ephemeral=True)
                except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
            button.callback=respond;self.add_item(button)
        button=discord.ui.Button(label='Open Session Planner',custom_id=f'pep:sessiondetail:{sid}')
        async def detail(interaction):
            if interaction.guild_id!=service.bot.config.guild_id:
                await interaction.response.send_message('Use this session in the club server.',ephemeral=True);return
            if service.base_url:
                token=service.store.issue_login(interaction.user.id)
                await interaction.response.send_message('Open your private Session Planner: '+service.base_url+'/planner/login?token='+token+'&session='+str(sid),ephemeral=True,suppress_embeds=True)
            else:
                await interaction.response.send_message(embed=render_embed(service.store,service.store.get(sid)),ephemeral=True)
        button.callback=detail;self.add_item(button)


class SessionService:
    def __init__(self,bot):
        self.bot=bot;self.store=SessionStore(bot.db,bot.config.guild_id);self.locks={};self.instance=os.urandom(16).hex()
        self.base_url=os.getenv('PEP_DASHBOARD_URL','').rstrip('/')

    async def identity(self,user_id):
        guild=self.bot.get_guild(self.bot.config.guild_id) or await self.bot.fetch_guild(self.bot.config.guild_id)
        member=await guild.fetch_member(int(user_id))
        manager=member.id==self.bot.config.owner_id or bool(set(self.bot.config.management_role_ids)&{r.id for r in member.roles})
        return member,manager

    def payload(self,sid):
        row=self.store.get(sid);attendees=self.store.attendance(sid)
        row['phase']=phase(row);row['attendance']=attendees
        row['counts']={s:sum(a['status']==s for a in attendees) for s in RESPONSES}
        row['post_url']=f'https://discord.com/channels/{row["guild_id"]}/{row["post_channel_id"]}/{row["message_id"]}' if row['message_id'] else None
        row['event_url']=f'https://discord.com/events/{row["guild_id"]}/{row["event_id"]}' if row['event_id'] else None
        return row

    def validate_post(self,data,sid=None,layout=None):
        checked=self.store.validate(dict(data))
        original=self.store
        class PreviewStore:
            def template(inner,tid):return {'layout':layout or original.template(tid)['layout']}
            def attendance(inner,unused):return original.attendance(sid) if sid else []
        render_embed(PreviewStore(),dict(checked,session_id=sid or 0,status='Scheduled'))
        return checked

    async def respond(self,sid,member,status,actor,manual=False):
        self.store.respond(sid,member.id,member.display_name,status,actor,manual)
        await self.sync(sid)

    async def sync(self,sid):
        async with self.locks.setdefault(sid,asyncio.Lock()):
            until=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
            with self.bot.db.connect() as conn:
                claimed=conn.execute('UPDATE team_sessions SET lease_owner=?,lease_until=? WHERE session_id=? AND guild_id=? AND (lease_until IS NULL OR lease_until<? OR lease_owner=?)',
                                     (self.instance,until,sid,str(self.bot.config.guild_id),utcnow(),self.instance)).rowcount
            if not claimed:return
            try:
                row=self.store.get(sid)
                channel=await self.bot.fetch_channel(int(row['post_channel_id']))
                if getattr(channel,'guild',None) is None or channel.guild.id!=self.bot.config.guild_id:
                    raise ValueError('Session post channel must belong to the club server.')
                embed=render_embed(self.store,row);view=RSVPView(self,sid)
                fingerprint=hashlib.sha256(json.dumps({'embed':embed.to_dict(),'view':view.to_components()},sort_keys=True).encode()).hexdigest()
                if not row['message_id']:
                    existing=None
                    if row['delivery_attempts']:
                        # Reconcile an interrupted send before ever creating another post.
                        async for message in channel.history(limit=None,after=datetime.fromisoformat(row['created_at'])):
                            if message.author.id==self.bot.user.id and any(e.footer.text.endswith(f'| Session #{sid}') for e in message.embeds if e.footer and e.footer.text):
                                existing=message;break
                    if existing:
                        message=existing;await message.edit(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
                    else:
                        self.bot.db.execute('UPDATE team_sessions SET delivery_attempts=delivery_attempts+1 WHERE session_id=?',(sid,))
                        message=await channel.send(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
                    self.bot.db.execute('UPDATE team_sessions SET message_id=?,embed_hash=? WHERE session_id=?',(str(message.id),fingerprint,sid))
                elif row['embed_hash']!=fingerprint:
                    message=await channel.fetch_message(int(row['message_id']))
                    await message.edit(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
                    self.bot.db.execute('UPDATE team_sessions SET embed_hash=? WHERE session_id=?',(fingerprint,sid))
                await self.sync_event(self.store.get(sid))
                self.bot.db.execute('UPDATE team_sessions SET sync_needed=0,sync_error=NULL,last_sync_at=? WHERE session_id=? AND revision=?',(utcnow(),sid,row['revision']))
            except (discord.HTTPException,ValueError) as error:
                self.bot.db.execute('UPDATE team_sessions SET sync_error=?,sync_needed=1,last_sync_at=? WHERE session_id=?',(str(error)[:400],utcnow(),sid))
                log.warning('Session sync held; session=%s error=%s',sid,type(error).__name__)
            finally:
                self.bot.db.execute('UPDATE team_sessions SET lease_owner=NULL,lease_until=NULL WHERE session_id=? AND lease_owner=?',(sid,self.instance))

    async def sync_event(self,row):
        guild=self.bot.get_guild(self.bot.config.guild_id) or await self.bot.fetch_guild(self.bot.config.guild_id)
        sid=row['session_id'];now=utcnow()
        if not row['event_id'] and (row['status']=='Cancelled' or row['start_at']<=now):return
        try:
            description=(('CANCELLED\n' if row['status']=='Cancelled' else '')+row['description']+'\nSession Planner: '+(self.base_url+'/planner/events/'+str(sid) if self.base_url else self.payload(sid)['post_url']))[:930]+f'\nPep Session #{sid}'
            args={'name':row['title'],'start_time':datetime.fromisoformat(row['start_at']),'end_time':datetime.fromisoformat(row['end_at']),'description':description}
            if row['voice_channel_id']:
                args.update(entity_type=discord.EntityType.voice,channel=await self.bot.fetch_channel(int(row['voice_channel_id'])))
            else:args.update(entity_type=discord.EntityType.external,location=row['location'])
            wanted=hashlib.sha256(json.dumps({**{k:str(v) for k,v in args.items()},'status':row['status']},sort_keys=True).encode()).hexdigest()
            if not row['event_id']:
                # Marker enables reconciliation after a crash between creation and ID save.
                args['description']=description
                events=await guild.fetch_scheduled_events()
                event=next((e for e in events if e.creator_id==self.bot.user.id and f'Pep Session #{sid}' in (e.description or '')),None)
                if not event:event=await guild.create_scheduled_event(**args,privacy_level=discord.PrivacyLevel.guild_only,reason='Pep Session Planner')
                self.bot.db.execute('UPDATE team_sessions SET event_id=? WHERE session_id=?',(str(event.id),sid))
            else:
                event=await guild.fetch_scheduled_event(int(row['event_id']))
                if row['status']=='Cancelled':
                    if event.status==discord.EventStatus.scheduled:await event.edit(name='CANCELLED — '+row['title'][:85],description=description,status=discord.EventStatus.cancelled)
                    elif event.status==discord.EventStatus.active:await event.edit(name='CANCELLED — '+row['title'][:85],description=description,status=discord.EventStatus.completed)
                elif phase(row)=='Past':
                    if event.status==discord.EventStatus.scheduled:await event.edit(status=discord.EventStatus.active)
                    if event.status in (discord.EventStatus.scheduled,discord.EventStatus.active):await event.edit(status=discord.EventStatus.completed)
                elif event.status not in (discord.EventStatus.cancelled,discord.EventStatus.completed):
                    if row['event_hash']!=wanted:await event.edit(**args)
                    if phase(row)=='In progress' and event.status==discord.EventStatus.scheduled:await event.edit(status=discord.EventStatus.active)
                else:
                    self.bot.db.execute('UPDATE team_sessions SET event_notice=? WHERE session_id=?',('Discord event is already closed; Pep keeps the updated planner without creating a duplicate.',sid));return
            self.bot.db.execute('UPDATE team_sessions SET event_hash=?,event_notice=NULL WHERE session_id=?',(wanted,sid))
        except discord.HTTPException as error:
            self.bot.db.execute('UPDATE team_sessions SET event_notice=? WHERE session_id=?',('Discord Events could not sync. Pep needs Create Events / Manage Events and access to the voice channel. '+str(error)[:200],sid))
            log.warning('Discord event sync unavailable; session=%s code=%s',sid,getattr(error,'code',None))

    async def tick(self):
        now=utcnow()
        self.bot.db.execute("UPDATE team_sessions SET status='Completed',sync_needed=1 WHERE guild_id=? AND status='Scheduled' AND end_at<=?",(str(self.bot.config.guild_id),now))
        rows=self.bot.db.rows("SELECT * FROM team_sessions WHERE guild_id=? AND (sync_needed=1 OR status='Scheduled') ORDER BY COALESCE(last_sync_at,'') LIMIT 20",(str(self.bot.config.guild_id),))
        for row in rows:await self.sync(row['session_id'])


def register_sessions(bot):
    service=bot.sessions
    group=app_commands.Group(name='session',description='Pep team sessions, availability and editable layouts')
    async def management(interaction):
        if not bot.manager(interaction):raise app_commands.CheckFailure('Approved management only.')
        if interaction.guild_id!=bot.config.guild_id:raise app_commands.CheckFailure('Use sessions in the club server.')
        return True
    async def club_member(interaction):
        if interaction.guild_id!=bot.config.guild_id:raise app_commands.CheckFailure('Use sessions in the club server.')
        return True
    def template_id(name,kind):
        default={'Tournament':'Cup / Tournament','Match':'Match Night','Scrim':'Scrim'}.get(kind,'Practice')
        wanted=name or default
        row=next((r for r in service.store.templates() if r['name'].casefold()==wanted.casefold()),None)
        if not row:raise ValueError('Choose a saved template from /session dashboard.')
        return row['template_id']
    async def suggestions(interaction,current):
        return [app_commands.Choice(name=r['name'],value=r['name']) for r in service.store.templates() if current.casefold() in r['name'].casefold()][:25]
    async def finish(interaction,row):
        await service.sync(row['session_id'])
        current=service.payload(row['session_id'])
        text=f"Session #{row['session_id']} saved."
        if current['post_url']:text+=' '+current['post_url']
        if current['sync_error']:text+='\nPost sync needs attention: '+current['sync_error']
        if current['event_notice']:text+='\n'+current['event_notice']
        await interaction.followup.send(text,ephemeral=True)
    @group.command(name='create',description='Create a team session and availability post')
    @app_commands.check(management)
    @app_commands.choices(session_type=[app_commands.Choice(name=k,value=k) for k in TYPES])
    @app_commands.autocomplete(template=suggestions)
    async def create(interaction,title:str,session_type:str,date:str,start_time:str,end_time:str,description:str='',location:str='Discord',required:bool=True,club:str='MPL Birmingham City',respond_by:str='',min_players:app_commands.Range[int,0,100]=0,lineup_note:str='',template:str='',channel:discord.TextChannel|None=None,voice_channel:discord.VoiceChannel|None=None,end_date:str='',notes:str=''):
        await interaction.response.defer(ephemeral=True)
        try:
            post=channel or interaction.channel
            if post.guild.id!=bot.config.guild_id or (voice_channel and voice_channel.guild.id!=bot.config.guild_id):raise ValueError('Choose channels in this club server.')
            deadline=local_time(*respond_by.split(' ',1)) if respond_by else None
            data={'title':title,'session_type':session_type,'start_at':local_time(date,start_time),'end_at':local_time(end_date or date,end_time),'description':description,'location':location,'required':int(required),'club':club,'deadline_at':deadline,'min_players':min_players,'lineup_note':lineup_note,'notes':notes,'template_id':template_id(template,session_type),'post_channel_id':str(post.id),'voice_channel_id':str(voice_channel.id) if voice_channel else None}
            service.validate_post(data)
            row=service.store.create(data,interaction.user.id,interaction.id)
            await finish(interaction,row)
        except (ValueError,TypeError) as error:await interaction.followup.send(str(error),ephemeral=True)
    @group.command(name='edit',description='Edit the same session, post and linked Discord event')
    @app_commands.check(management)
    @app_commands.choices(session_type=[app_commands.Choice(name=k,value=k) for k in TYPES])
    @app_commands.autocomplete(template=suggestions)
    async def edit(interaction,session_id:int,title:str|None=None,session_type:str|None=None,date:str|None=None,start_time:str|None=None,end_time:str|None=None,end_date:str|None=None,description:str|None=None,location:str|None=None,required:bool|None=None,club:str|None=None,respond_by:str|None=None,min_players:app_commands.Range[int,0,100]|None=None,lineup_note:str|None=None,template:str|None=None,voice_channel:discord.VoiceChannel|None=None,notes:str|None=None):
        await interaction.response.defer(ephemeral=True)
        try:
            row=service.store.get(session_id);changes={}
            for k,v in [('title',title),('session_type',session_type),('description',description),('location',location),('required',required),('club',club),('min_players',min_players),('lineup_note',lineup_note),('notes',notes)]:
                if v is not None:changes[k]=v
            old_start=datetime.fromisoformat(row['start_at']).astimezone(ET);old_end=datetime.fromisoformat(row['end_at']).astimezone(ET)
            if date or start_time:changes['start_at']=local_time(date or old_start.date().isoformat(),start_time or old_start.strftime('%H:%M'))
            if date or end_date or end_time:changes['end_at']=local_time(end_date or date or old_end.date().isoformat(),end_time or old_end.strftime('%H:%M'))
            if respond_by is not None:changes['deadline_at']=local_time(*respond_by.split(' ',1)) if respond_by else None
            if voice_channel:
                if voice_channel.guild.id!=bot.config.guild_id:raise ValueError('Choose a club voice channel.')
                changes['voice_channel_id']=str(voice_channel.id)
            if template:changes['template_id']=template_id(template,session_type or row['session_type'])
            service.validate_post({**{k:row[k] for k in ('title','session_type','start_at','end_at','description','location','voice_channel_id','post_channel_id','club','required','deadline_at','min_players','lineup_note','notes','template_id')},**changes},session_id)
            await finish(interaction,service.store.edit(session_id,changes,interaction.user.id,row['revision']))
        except (ValueError,TypeError) as error:await interaction.followup.send(str(error),ephemeral=True)
    @group.command(name='cancel',description='Mark a session cancelled and update its post/event')
    @app_commands.check(management)
    async def cancel(interaction,session_id:int,reason:str=''):
        await interaction.response.defer(ephemeral=True)
        try:await finish(interaction,service.store.cancel(session_id,interaction.user.id,reason))
        except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
    @group.command(name='attendance',description='Management correction of a player’s availability')
    @app_commands.check(management)
    @app_commands.choices(status=[app_commands.Choice(name=k,value=k) for k in RESPONSES])
    async def attendance(interaction,session_id:int,player:discord.Member,status:str):
        await interaction.response.defer(ephemeral=True)
        try:
            if player.guild.id!=bot.config.guild_id:raise ValueError('Choose a club member.')
            await service.respond(session_id,player,status,interaction.user.id,True)
            await interaction.followup.send('Player availability updated.',ephemeral=True)
        except ValueError as error:await interaction.followup.send(str(error),ephemeral=True)
    @group.command(name='view',description='Open the full session post')
    @app_commands.check(club_member)
    async def view(interaction,session_id:int):
        try:await interaction.response.send_message(embed=render_embed(service.store,service.store.get(session_id)),view=RSVPView(service,session_id),ephemeral=True)
        except ValueError as error:await interaction.response.send_message(str(error),ephemeral=True)
    @group.command(name='events',description='Upcoming and past team sessions')
    @app_commands.check(club_member)
    async def events(interaction):
        rows=[service.payload(s['session_id']) for s in service.store.list()]
        lines=[]
        for heading,wanted in [('UPCOMING',('Upcoming','In progress')),('PAST / CANCELLED',('Past','Cancelled'))]:
            lines.append(heading)
            for row in [s for s in rows if s['phase'] in wanted][:10]:
                lines.append(f"#{row['session_id']} {row['title']} • {row['session_type']} • {format_time(row['start_at'],'discord')} • ✅ {row['counts']['Available']} ❓ {row['counts']['Maybe']} ❌ {row['counts']['Unavailable']} • {row['club']} • {row['phase']}\n{row['post_url'] or 'Post pending'}")
        await interaction.response.send_message('\n'.join(lines)[:1900] or 'No team sessions yet.',ephemeral=True)
    @group.command(name='dashboard',description='Private Events dashboard and management layout editor')
    @app_commands.check(club_member)
    async def dashboard(interaction):
        if not service.base_url:
            await interaction.response.send_message('The dashboard address is not configured yet. Management can still use the other /session commands.',ephemeral=True);return
        token=service.store.issue_login(interaction.user.id)
        await interaction.response.send_message('Your private sign-in link works once and expires in 10 minutes.\n'+service.base_url+'/planner/login?token='+token,ephemeral=True,suppress_embeds=True)
    bot.tree.add_command(group)
