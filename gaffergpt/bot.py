"""Discord adapter: all football records live in the shared SQLite database."""
import asyncio
import io
import logging
import math
import sys
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from .config import Config
from .feedback import player_feedback
from .analysis import FactualGaffer, tracking_text
from .database import Database, utcnow
from .parser import parse_recap, parse_registration
from .reporter import Reporter, match_label
from .scheduler import WeeklyScheduler, week_window

log=logging.getLogger('gaffergpt')


class ManagedView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot=bot

    async def interaction_check(self, interaction):
        if not self.bot.manager(interaction):
            await interaction.response.send_message('This control is for management.',ephemeral=True)
            return False
        return True

    async def on_error(self, interaction, error, item):
        log.error('Control failed: %s',type(error).__name__)
        if not interaction.response.is_done():
            await interaction.response.send_message('That action failed. Your saved records are safe; please try again.',ephemeral=True)
        else:
            await interaction.followup.send('That action failed. Please try again.',ephemeral=True)


class Action(discord.ui.Button):
    def __init__(self, label, key, handler, style=discord.ButtonStyle.secondary, row=None):
        super().__init__(label=label,custom_id=key,style=style,row=row)
        self.handler=handler

    async def callback(self, interaction):
        await self.handler(interaction)


class ReviewView(ManagedView):
    def __init__(self, bot, match_id):
        super().__init__(bot)
        self.match_id=match_id
        for label,kind,venue in [('Official Home','Official','Home'),('Official Away','Official','Away'),('Practice / Scrimmage','Practice','Unknown'),('Ignore','Ignored','Unknown')]:
            async def choose(interaction,k=kind,v=venue):
                bot.db.classify(match_id,k,v,interaction.user.id)
                await interaction.response.edit_message(content=f'Match #{match_id}: {match_label(bot.db.match(match_id))}\nClassified as {k}.',view=self)
            self.add_item(Action(label,f'gaffer:classify:{match_id}:{kind}:{venue}',choose))


class MatchSelect(discord.ui.Select):
    def __init__(self, view, matches, kind, selected):
        self.parent_view=view
        self.page_ids=[m['match_id'] for m in matches]
        super().__init__(placeholder=kind,custom_id=f'gaffer:select:{view.report_id}:{view.page}:{kind}',
            min_values=0,max_values=len(matches),
            options=[discord.SelectOption(label=f"#{m['match_id']} {match_label(m)}"[:100],value=str(m['match_id']),default=m['match_id'] in selected) for m in matches])

    async def callback(self, interaction):
        view=self.parent_view
        view.bot.db.replace_page_selection(view.report_id,self.page_ids,[int(v) for v in self.values])
        await interaction.response.edit_message(content=view.bot.report_summary(view.report_id),view=ReportView(view.bot,view.report_id,view.page))


class ReportView(ManagedView):
    def __init__(self, bot, report_id, page=0):
        super().__init__(bot)
        self.report_id=report_id; self.page=page
        report=bot.db.report(report_id)
        if not report or report['status'] in ('skipped','approved'):
            return
        eligible=bot.db.period_matches(report['week_start'],report['week_end'],True)
        # 20 per page keeps both menus under Discord's 25-option limit.
        total=max(1,(len(eligible)+19)//20)
        self.page=min(max(page,0),total-1)
        page_matches=eligible[self.page*20:(self.page+1)*20]
        selected={m['match_id'] for m in bot.db.selected(report_id)}
        for kind in ('Official','Practice'):
            rows=[m for m in page_matches if m['match_type']==kind]
            if rows:
                self.add_item(MatchSelect(self,rows,kind,selected))
        async def generate(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Coach must confirm the article selections.',ephemeral=True); return
            try:
                bot.db.confirm_report(report_id)
            except ValueError as error:
                await interaction.response.send_message(str(error),ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            article=await asyncio.to_thread(bot.reporter.generate,report_id)
            owner=await bot.fetch_user(bot.config.owner_id)
            await owner.send(content=f'RT Football Media draft #{report_id} — review only. Nothing has been published.',
                file=discord.File(io.BytesIO(article.encode()),filename=f'RT_Report_{report_id}.txt'),view=DraftView(bot,report_id),allowed_mentions=discord.AllowedMentions.none())
            bot.db.execute('UPDATE weekly_reports SET draft_sent_at=? WHERE report_id=?',(utcnow(),report_id))
            await interaction.followup.send('Draft sent to Coach for review.',ephemeral=True)
        async def development(interaction):
            bot.db.execute("UPDATE weekly_reports SET include_development=1-include_development,status='selecting',article=NULL,observations=NULL WHERE report_id=?",(report_id,))
            await interaction.response.edit_message(content=bot.report_summary(report_id),view=ReportView(bot,report_id,self.page))
        async def remind(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can schedule his reminder.',ephemeral=True); return
            bot.scheduler.remind(report_id,datetime.now(timezone.utc))
            await interaction.response.send_message('I’ll remind you in one hour.',ephemeral=True)
        async def skip(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can skip the week.',ephemeral=True); return
            bot.scheduler.skip(report_id)
            await interaction.response.edit_message(content='This week is skipped. Your match records remain saved.',view=None)
        async def review(interaction):
            await interaction.response.defer(ephemeral=True)
            unknown=[m for m in bot.db.period_matches(report['week_start'],report['week_end']) if m['match_type']=='Unknown']
            if not unknown:
                await interaction.followup.send('No unclassified matches remain.',ephemeral=True)
            for m in unknown[:10]:
                await interaction.followup.send(f"Review #{m['match_id']}: {match_label(m)}",view=ReviewView(bot,m['match_id']),ephemeral=True)
        self.add_item(Action('Generate Report',f'gaffer:generate:{report_id}',generate,discord.ButtonStyle.primary,row=2))
        self.add_item(Action('Training Ground: '+('ON' if report['include_development'] else 'OFF'),f'gaffer:development:{report_id}',development,row=2))
        self.add_item(Action('Review Unknown Matches',f'gaffer:unknown:{report_id}',review,row=2))
        self.add_item(Action('Remind Me Later',f'gaffer:remind:{report_id}',remind,row=3))
        self.add_item(Action('Skip This Week',f'gaffer:skip:{report_id}',skip,row=3))
        for label,target in [('Previous Page',self.page-1),('Next Page',self.page+1)]:
            if 0<=target<total:
                async def move(interaction,p=target):
                    await interaction.response.edit_message(content=bot.report_summary(report_id),view=ReportView(bot,report_id,p))
                self.add_item(Action(label,f'gaffer:page:{report_id}:{self.page}:{target}',move,row=3))


class DraftView(ManagedView):
    def __init__(self, bot, report_id):
        super().__init__(bot)
        async def approve(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can approve this draft.',ephemeral=True); return
            with bot.db.connect() as conn:
                cur=conn.execute("UPDATE weekly_reports SET status='approved' WHERE report_id=? AND status='draft'",(report_id,))
            await interaction.response.send_message('Approved and saved. Nothing was published.' if cur.rowcount else 'This draft has changed. Generate a fresh draft.',ephemeral=True)
        async def change(interaction):
            if bot.db.report(report_id)['status']=='skipped':
                await interaction.response.send_message('This week was skipped.',ephemeral=True); return
            bot.db.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id=?",(report_id,))
            await interaction.response.send_message(bot.report_summary(report_id),view=ReportView(bot,report_id),ephemeral=True)
        self.add_item(Action('Approve Draft (save only)',f'gaffer:approve:{report_id}',approve,discord.ButtonStyle.success))
        self.add_item(Action('Change Selection',f'gaffer:change:{report_id}',change))


class DiscordDelivery:
    def __init__(self, bot):
        self.bot=bot

    async def channel(self):
        owner=await self.bot.fetch_user(self.bot.config.owner_id)
        return owner.dm_channel or await owner.create_dm()

    async def find(self, marker):
        channel=await self.channel()
        # Do not impose a small history cap: crash recovery must find older sends.
        async for message in channel.history(limit=None,after=datetime.fromisoformat(self.bot.db.setting('scheduler_first_week'))):
            if message.author.id==self.bot.user.id and any(e.footer.text==marker for e in message.embeds if e.footer):
                return message.id
        return None

    async def send(self, report_id, marker):
        channel=await self.channel()
        embed=discord.Embed(title='PEP — WEEKLY RECAP',description=self.bot.report_summary(report_id))
        embed.set_footer(text=marker)
        message=await channel.send(embed=embed,view=ReportView(self.bot,report_id),allowed_mentions=discord.AllowedMentions.none())
        return message.id


class GafferBot(discord.Client):
    def __init__(self, config):
        intents=discord.Intents.default(); intents.message_content=True
        super().__init__(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        self.config=config; self.db=Database(config.database_path)
        # Optional first-run owner link; never overwrite a later correction.
        if config.owner_player_name and not self.db.player_link(config.owner_id) and not self.db.setting('owner_link_seeded'):
            try:
                self.db.link_player(config.owner_id,'Coach',config.owner_player_name,config.owner_id)
                self.db.set_setting('owner_link_seeded','true')
            except ValueError:
                log.warning('Owner player link needs management correction.')
        self.reporter=Reporter(self.db)
        self.tree=app_commands.CommandTree(self)
        self.scheduler=WeeklyScheduler(self.db,config.owner_id,DiscordDelivery(self))
        self.worker=None
        self.register_commands()

    def manager(self, interaction):
        if interaction.user.id==self.config.owner_id:
            return interaction.guild_id in (None,self.config.guild_id)
        return interaction.guild_id==self.config.guild_id and bool(set(self.config.management_role_ids)&{r.id for r in getattr(interaction.user,'roles',[])})

    async def setup_hook(self):
        for m in self.db.rows('SELECT match_id FROM matches'):
            self.add_view(ReviewView(self,m['match_id']))
        for report in self.db.rows("SELECT * FROM weekly_reports WHERE status!='skipped'"):
            eligible=self.db.period_matches(report['week_start'],report['week_end'],True)
            for page in range(max(1,(len(eligible)+19)//20)):
                self.add_view(ReportView(self,report['report_id'],page))
            self.add_view(DraftView(self,report['report_id']))
        guild=discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.worker=asyncio.create_task(self.work())

    async def work(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                # Always seed persisted jobs; production delivery remains gated.
                now=datetime.now(timezone.utc)
                self.scheduler.seed(now)
                if self.config.schedule_enabled:
                    await self.scheduler.tick(now)
                await self.scheduler.tick_tests(now)
                await self.recover_recaps()
                await self.pending_reviews()
            except Exception as error:
                log.error('Background check failed: %s',type(error).__name__)
            await asyncio.sleep(30)

    async def on_error(self, event_method, *args, **kwargs):
        error=sys.exc_info()[1]
        log.error('Discord event %s failed: %s',event_method,type(error).__name__)

    async def on_ready(self):
        log.info('Pep connected; guild=%s schedule=%s',self.config.guild_id,self.config.schedule_enabled)

    async def close(self):
        if self.worker:
            self.worker.cancel()
        await super().close()

    def recap_config(self):
        channel=int(self.db.setting('recap_channel',self.config.recap_channel_id))
        author=int(self.db.setting('recap_author',self.config.source_bot_id))
        return channel,author

    async def ingest_message(self,message):
        channel,author=self.recap_config()
        if not channel or not author or not message.guild or message.guild.id!=self.config.guild_id:
            return
        if message.channel.id!=channel or message.author.id!=author or not message.content.strip():
            return
        self.db.ingest(message.id,channel,message.guild.id,message.created_at.astimezone(timezone.utc).isoformat(),message.content,parse_recap(message.content))

    async def recover_recaps(self):
        channel_id,author=self.recap_config()
        if not channel_id or not author:
            return
        channel=self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        cursor=self.db.setting(f'cursor:{channel_id}')
        if cursor is None:
            # Configuration records the starting point; don't import unrelated old history.
            self.db.set_setting(f'cursor:{channel_id}',str(discord.utils.time_snowflake(datetime.now(timezone.utc))))
            return
        async for message in channel.history(limit=None,after=discord.Object(id=int(cursor)),oldest_first=True):
            await self.ingest_message(message)
            self.db.set_setting(f'cursor:{channel_id}',str(message.id))

    async def pending_reviews(self):
        for m in self.db.rows("SELECT * FROM matches WHERE review_message_id IS NULL AND match_type='Unknown' ORDER BY match_id LIMIT 10"):
            owner=await self.fetch_user(self.config.owner_id)
            marker=f"gaffer:review:{m['match_id']}"
            channel=owner.dm_channel or await owner.create_dm()
            existing=None
            async for message in channel.history(limit=None,after=datetime.fromisoformat(m['detected_at'])):
                if message.author.id==self.user.id and any(e.footer.text==marker for e in message.embeds if e.footer):
                    existing=message; break
            if existing is None:
                embed=discord.Embed(title=f"Match Review #{m['match_id']}",description=match_label(m)+'\nStarts Unknown. Choose its classification below.')
                embed.set_footer(text=marker)
                existing=await owner.send(embed=embed,view=ReviewView(self,m['match_id']))
            self.db.execute('UPDATE matches SET review_message_id=? WHERE match_id=?',(str(existing.id),m['match_id']))

    async def on_message(self,message):
        await self.ingest_message(message)
        if message.author.bot or not message.guild or message.guild.id!=self.config.guild_id:
            return
        parsed=parse_registration(message.content)
        if parsed:
            self.db.register_player(message.author.id,message.author.name,*parsed)
            await message.reply(f'Saved your preferred position: {parsed[0]}; role: {parsed[1]}.',mention_author=False)

    def report_summary(self, report_id):
        report=self.db.report(report_id)
        rows=self.db.period_matches(report['week_start'],report['week_end'],True)
        selected={m['match_id'] for m in self.db.selected(report_id)}
        unknown=sum(m['match_type']=='Unknown' for m in self.db.period_matches(report['week_start'],report['week_end']))
        lines=['Morning Coach. Choose the matches for your Birmingham City report.','Week: '+report['week_start'][:10]+' to '+report['week_end'][:10]+' (end exclusive).']
        for kind,title in [('Official','OFFICIAL MATCHES'),('Practice','PRACTICE / DEVELOPMENT')]:
            lines+=['',title]
            group=[m for m in rows if m['match_type']==kind]
            lines.extend(('☑' if m['match_id'] in selected else '☐')+f" #{m['match_id']} {match_label(m)}" for m in group[:4])
            if len(group)>4:
                lines.append(f'{len(group)-4} more available in the paged selection menus.')
            if not group:
                lines.append('No classified matches available.')
        lines+=['',f'Training Ground section: {"ON" if report["include_development"] else "OFF"}.']
        if unknown:
            lines.append(f'⚠ {unknown} matches still need classification. Use Review Unknown Matches.')
        lines.append('Selections are saved as you choose. Generate Report confirms them and sends a private draft.')
        return '\n'.join(lines)[:1900]

    def register_commands(self):
        async def authorized(interaction):
            if not self.manager(interaction):
                raise app_commands.CheckFailure('Management only.')
            return True

        async def player_server(interaction):
            if interaction.guild_id!=self.config.guild_id:
                raise app_commands.CheckFailure('Use player commands in the club server.')
            return True

        @self.tree.command(name='linkplayer',description='Connect your Discord account to your exact OurProClubs player name')
        @app_commands.check(player_server)
        async def linkplayer(interaction,player_name:str):
            try:
                link=self.db.link_player(interaction.user.id,interaction.user.name,player_name,interaction.user.id)
                text=f"Linked you to **{discord.utils.escape_markdown(link['player_name'])}**. This is your supplied stats name; it does not grant server roles. Use /myplayer to check it."
            except ValueError as error:
                text=str(error)
            await interaction.response.send_message(text,ephemeral=True)

        @self.tree.command(name='myfeedback',description='Get private coaching feedback from your classified match stats')
        @app_commands.check(player_server)
        async def myfeedback(interaction):
            text=player_feedback(self.db,interaction.user.id)
            if len(text)<=1900:
                await interaction.response.send_message(text,ephemeral=True)
            else:
                await interaction.response.send_message('Your private player feedback:',file=discord.File(io.BytesIO(text.encode()),filename='pep-player-feedback.txt'),ephemeral=True)

        @self.tree.command(name='myplayer',description='Check which stats name is linked to you')
        @app_commands.check(player_server)
        async def myplayer(interaction):
            link=self.db.player_link(interaction.user.id)
            text=f"Your stats name: **{discord.utils.escape_markdown(link['player_name'])}**. Use /linkplayer to correct it or /unlinkplayer to remove it." if link else 'No player name linked yet. Use /linkplayer with your exact name from OurProClubs.'
            await interaction.response.send_message(text,ephemeral=True)

        @self.tree.command(name='unlinkplayer',description='Remove your player-name link without deleting match stats')
        @app_commands.check(player_server)
        async def unlinkplayer(interaction):
            self.db.unlink_player(interaction.user.id)
            await interaction.response.send_message('Your player link is removed. Saved match stats remain safe.',ephemeral=True)

        @self.tree.command(name='setplayerlink',description='Management: correct or remove a member’s stats-name link')
        @app_commands.check(authorized)
        async def setplayerlink(interaction,member:discord.Member,player_name:str=''):
            if member.guild.id!=self.config.guild_id or member.bot:
                await interaction.response.send_message('Choose a player in this club server.',ephemeral=True); return
            try:
                if player_name:
                    link=self.db.link_player(member.id,member.name,player_name,interaction.user.id)
                    text=f"Saved {discord.utils.escape_markdown(member.display_name)} → {discord.utils.escape_markdown(link['player_name'])}."
                else:
                    self.db.unlink_player(member.id)
                    text='Removed the link. Match stats remain saved.'
            except ValueError as error:
                text=str(error)
            await interaction.response.send_message(text,ephemeral=True)

        @self.tree.command(name='development',description='Management: compare classified practices and official performances')
        @app_commands.check(authorized)
        async def development(interaction,days:app_commands.Range[int,1,90]=30):
            now=datetime.now(timezone.utc)
            matches=self.db.period_matches((now-timedelta(days=days)).isoformat(),now.isoformat())
            matches=[m for m in matches if m['match_type'] in ('Official','Practice')]
            statistics=[]
            for m in matches:
                statistics.extend(self.db.rows('SELECT * FROM match_statistics WHERE match_id=?',(m['match_id'],)))
            text=tracking_text(FactualGaffer().analyze(matches,statistics))
            await interaction.response.send_message(f'Private development review for the last {days} days:',
                file=discord.File(io.BytesIO(text.encode()),filename='pep-development.txt'),ephemeral=True)

        @self.tree.command(name='status',description='Check Pep and the match review queue')
        @app_commands.check(authorized)
        async def status(interaction):
            unknown=self.db.one("SELECT COUNT(*) AS n FROM matches WHERE match_type='Unknown'")['n']
            await interaction.response.send_message(f'Pep is online. {unknown} matches await review. Friday reminders: {"enabled" if self.config.schedule_enabled else "test mode"}.',ephemeral=True)

        @self.tree.command(name='configurepep',description='Choose the OurProClubs text recap channel and source bot')
        @app_commands.check(authorized)
        async def configure(interaction,channel:discord.TextChannel,source_bot:discord.Member):
            if interaction.user.id!=self.config.owner_id:
                await interaction.response.send_message('Only Coach can change the listener settings.',ephemeral=True); return
            if channel.guild.id!=self.config.guild_id or not source_bot.bot:
                await interaction.response.send_message('Choose a channel in this server and the actual OurProClubs bot.',ephemeral=True); return
            self.db.set_setting('recap_channel',channel.id); self.db.set_setting('recap_author',source_bot.id)
            if self.db.setting(f'cursor:{channel.id}') is None:
                self.db.set_setting(f'cursor:{channel.id}',discord.utils.time_snowflake(datetime.now(timezone.utc)))
            await interaction.response.send_message('Saved. Future text recaps from that bot will enter the Unknown queue.',ephemeral=True)

        @self.tree.command(name='matches',description='List recent saved matches and their classifications')
        @app_commands.check(authorized)
        async def matches(interaction):
            rows=self.db.rows('SELECT * FROM matches ORDER BY played_at DESC,match_id DESC LIMIT 15')
            await interaction.response.send_message('\n'.join(f"#{m['match_id']} {match_label(m)} [{m['match_type']}]" for m in rows)[:1900] or 'No matches saved yet.',ephemeral=True)

        @self.tree.command(name='reviewmatches',description='Review the next ten unclassified matches')
        @app_commands.check(authorized)
        async def reviewmatches(interaction):
            await interaction.response.defer(ephemeral=True)
            rows=self.db.rows("SELECT * FROM matches WHERE match_type='Unknown' ORDER BY match_id LIMIT 10")
            if not rows:
                await interaction.followup.send('All matches are classified.',ephemeral=True)
            for m in rows:
                await interaction.followup.send(f"#{m['match_id']} {match_label(m)}",view=ReviewView(self,m['match_id']),ephemeral=True)

        @self.tree.command(name='match',description='Inspect or correct the classification of one match')
        @app_commands.check(authorized)
        async def match(interaction,match_id:int):
            m=self.db.match(match_id)
            if not m:
                await interaction.response.send_message('Match not found.',ephemeral=True); return
            await interaction.response.send_message(f"#{match_id} {match_label(m)}\n{m['match_type']}\nRaw recap:\n{m['raw_recap'][:1400]}",view=ReviewView(self,match_id),ephemeral=True)

        @self.tree.command(name='matchdetails',description='Correct missing opponent, scores and competition')
        @app_commands.check(authorized)
        async def matchdetails(interaction,match_id:int,opponent:str,birmingham_score:app_commands.Range[int,0,99],opponent_score:app_commands.Range[int,0,99],competition:str=''):
            if not self.db.match(match_id):
                await interaction.response.send_message('Match not found.',ephemeral=True); return
            with self.db.connect() as conn:
                conn.execute('UPDATE matches SET opponent=?,birmingham_score=?,opponent_score=?,competition=? WHERE match_id=?',(opponent,birmingham_score,opponent_score,competition or None,match_id))
                conn.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id IN (SELECT report_id FROM report_matches WHERE match_id=?)",(match_id,))
            await interaction.response.send_message('Facts updated; affected drafts need to be regenerated.',ephemeral=True)

        @self.tree.command(name='matchstat',description='Store a verified team/player statistic for a match')
        @app_commands.check(authorized)
        @app_commands.choices(subject_type=[app_commands.Choice(name='Team',value='team'),app_commands.Choice(name='Player',value='player')])
        async def matchstat(interaction,match_id:int,subject_type:str,subject:str,metric:str,value:float,unit:str=''):
            if not self.db.match(match_id):
                await interaction.response.send_message('Match not found.',ephemeral=True); return
            if not math.isfinite(value) or value<0:
                await interaction.response.send_message('Use a finite, nonnegative statistic.',ephemeral=True); return
            self.db.execute('''INSERT INTO match_statistics(match_id,subject_type,subject_key,metric,value,unit) VALUES (?,?,?,?,?,?)
             ON CONFLICT(match_id,subject_type,subject_key,metric) DO UPDATE SET value=excluded.value,unit=excluded.unit''',
             (match_id,subject_type,subject,metric.strip().casefold(),value,unit))
            self.db.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id IN (SELECT report_id FROM report_matches WHERE match_id=?)",(match_id,))
            await interaction.response.send_message('Statistic saved. Affected drafts need to be regenerated.',ephemeral=True)

        @self.tree.command(name='weeklyreport',description='Select exactly which matches belong in a weekly draft')
        @app_commands.check(authorized)
        async def weeklyreport(interaction,start_date:str='',end_date:str=''):
            a,b=week_window(datetime.now(timezone.utc))
            if start_date or end_date:
                from .scheduler import ET
                try:
                    a=datetime.strptime(start_date,'%Y-%m-%d').replace(tzinfo=ET).astimezone(timezone.utc).isoformat()
                    b=datetime.strptime(end_date,'%Y-%m-%d').replace(tzinfo=ET).astimezone(timezone.utc).isoformat()
                    if a>=b:
                        raise ValueError()
                except ValueError:
                    await interaction.response.send_message('Use YYYY-MM-DD for both dates. End date is exclusive and must be later.',ephemeral=True); return
            report=self.db.open_report(a,b,self.config.owner_id)
            await interaction.response.send_message(self.report_summary(report['report_id']),view=ReportView(self,report['report_id']),ephemeral=True)

        @self.tree.command(name='tactic',description='Save or update a named squad tactic')
        @app_commands.check(authorized)
        async def tactic(interaction,name:str,formation:str,build_up:str,depth:app_commands.Range[int,0,100],instructions:str=''):
            self.db.execute('''INSERT INTO squad_tactics(tactic_name,formation,build_up_style,defensive_depth,custom_instructions) VALUES (?,?,?,?,?)
             ON CONFLICT(tactic_name) DO UPDATE SET formation=excluded.formation,build_up_style=excluded.build_up_style,
             defensive_depth=excluded.defensive_depth,custom_instructions=excluded.custom_instructions''',
             (name,formation,build_up,depth,instructions or None))
            await interaction.response.send_message(f'Saved tactic: {name}.',ephemeral=True)

        @self.tree.command(name='officialrecord',description='Show the record from classified official matches only')
        @app_commands.check(authorized)
        async def officialrecord(interaction):
            r=self.db.official_record()
            await interaction.response.send_message(f"Official record: {r['wins']} wins, {r['draws']} draws, {r['losses']} losses. {r['played']} matches with verified scores.",ephemeral=True)

        @self.tree.command(name='testweeklydm',description='Owner-only: test weekly DM delivery without enabling Friday jobs')
        @app_commands.check(authorized)
        async def testweeklydm(interaction):
            if interaction.user.id!=self.config.owner_id:
                await interaction.response.send_message('Only Coach can run this test.',ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            now=datetime.now(timezone.utc)
            self.scheduler.seed(now)
            report=self.db.open_report(*week_window(now),self.config.owner_id)
            self.scheduler.schedule_test(now)
            await interaction.followup.send('One-minute scheduler test queued. The DM should arrive within 90 seconds. Friday scheduling remains disabled unless PEP_FRIDAY_RECAP is true.',ephemeral=True)

        @self.tree.error
        async def command_error(interaction,error):
            log.error('Command failed: %s',type(error).__name__)
            text=str(error) if isinstance(error,app_commands.CheckFailure) else 'That action failed. Your records are safe; please try again.'
            if interaction.response.is_done():
                await interaction.followup.send(text,ephemeral=True)
            else:
                await interaction.response.send_message(text,ephemeral=True)


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    config=Config.load()
    GafferBot(config).run(config.token,log_handler=None)


if __name__=='__main__':
    main()
