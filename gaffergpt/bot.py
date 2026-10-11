"""Discord adapter: all football records live in the shared SQLite database."""
import asyncio
import io
import json
import logging
import math
import sys
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from .config import Config
from .notebook import notebook, daily_backup
from .google_notebook import GoogleNotebook
from .media_api import start_api
from .feedback import player_feedback
from .analysis import FactualGaffer, tracking_text
from .database import Database, utcnow
from .parser import parse_recap, parse_registration, is_match_recap, is_setup_prompt
from .recap_check import readable_message, inspect_league_stats
from .reporter import Reporter, match_label
from .scheduler import WeeklyScheduler, week_window
from .session_reviews import SessionReviews
from .tactical_coach import PracticalCoach
from .coaching_ai import OpenAICoach

log=logging.getLogger('gaffergpt')
PEP_FOOTER='Pep • Birmingham Tactical Coach 🔵 | Keep Right On'


def branded_footer(marker):
    # Retain the existing reference used to prevent duplicate review/reminder DMs.
    return PEP_FOOTER+'\n'+marker


def has_marker(embed,marker):
    text=embed.footer.text if embed.footer else None
    return text==marker or text==branded_footer(marker)


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


class SessionMatchView(ManagedView):
    def __init__(self, bot, batch_id, page=0):
        super().__init__(bot)
        rows=bot.session_reviews.matches(batch_id)
        total=max(1,(len(rows)+19)//20)
        page=min(max(page,0),total-1)
        matches=rows[page*20:(page+1)*20]
        if matches:
            menu=discord.ui.Select(placeholder='Choose a match to review',
                custom_id=f'pep:session-select:{batch_id}:{page}',
                options=[discord.SelectOption(label=f"#{m['match_id']} {match_label(m)} [{m['match_type']}]"[:100],value=str(m['match_id'])) for m in matches])
            async def choose(interaction):
                mid=int(menu.values[0]); m=bot.db.match(mid)
                await interaction.response.send_message(f"Match #{mid}: {match_label(m)}",view=ReviewView(bot,mid),ephemeral=True)
            menu.callback=choose
            self.add_item(menu)
        for label,target in [('Previous',page-1),('Next',page+1)]:
            if 0<=target<total:
                async def move(interaction,p=target):
                    await interaction.response.edit_message(content=f'Session matches — page {p+1}',view=SessionMatchView(bot,batch_id,p))
                self.add_item(Action(label,f'pep:session-page:{batch_id}:{page}:{target}',move))


class SessionReviewView(ManagedView):
    def __init__(self, bot, batch_id):
        super().__init__(bot)
        async def review(interaction):
            await interaction.response.send_message('Choose a session match. Saved classifications are shown in the menu.',
                view=SessionMatchView(bot,batch_id),ephemeral=True)
        self.add_item(Action('Review Session Matches',f'pep:session-review:{batch_id}',review))


class SessionDelivery:
    def __init__(self, bot):
        self.bot=bot

    async def channel(self):
        owner=await self.bot.fetch_user(self.bot.config.owner_id)
        return owner.dm_channel or await owner.create_dm()

    async def find(self, marker, created_at):
        channel=await self.channel()
        async for message in channel.history(limit=None,after=datetime.fromisoformat(created_at)):
            if message.author.id==self.bot.user.id and any(has_marker(e,marker) for e in message.embeds):
                return message.id
        return None

    async def send(self, batch_id, marker):
        rows=self.bot.session_reviews.matches(batch_id)
        lines=[f"Session ready for review: {len(rows)} saved matches.",
               'Choose each match below. Nothing counts as official or practice until classified.','']
        lines.extend(f"#{m['match_id']} {match_label(m)}" for m in rows[:10])
        if len(rows)>10:
            lines.append('All remaining matches are available in the paged review menu.')
        embed=discord.Embed(title='PEP — SESSION REVIEW',description='\n'.join(lines)[:3900])
        embed.set_footer(text=branded_footer(marker))
        channel=await self.channel()
        message=await channel.send(embed=embed,view=SessionReviewView(self.bot,batch_id),allowed_mentions=discord.AllowedMentions.none())
        return message.id


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
            if message.author.id==self.bot.user.id and any(has_marker(e,marker) for e in message.embeds):
                return message.id
        return None

    async def send(self, report_id, marker):
        channel=await self.channel()
        embed=discord.Embed(title='PEP — WEEKLY RECAP',description=self.bot.report_summary(report_id))
        embed.set_footer(text=branded_footer(marker))
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
        self.session_reviews=SessionReviews(self.db,config.session_quiet_minutes)
        self.session_review_lock=asyncio.Lock()
        self.coach=OpenAICoach.from_environment()
        self.coaching_lock=asyncio.Lock()
        self.reporter=Reporter(self.db)
        self.tree=app_commands.CommandTree(self)
        self.scheduler=WeeklyScheduler(self.db,config.owner_id,DiscordDelivery(self))
        self.worker=None
        self.notebook_worker=None
        self.media_runner=None
        self.register_commands()

    def manager(self, interaction):
        if interaction.user.id==self.config.owner_id:
            return interaction.guild_id in (None,self.config.guild_id)
        return interaction.guild_id==self.config.guild_id and bool(set(self.config.management_role_ids)&{r.id for r in getattr(interaction.user,'roles',[])})

    async def setup_hook(self):
        if self.config.reporter_secret:
            self.media_runner=await start_api(self.db,self.config.reporter_secret,self.config.reporter_port)
        for batch in self.db.rows('SELECT batch_id FROM session_reviews WHERE message_id IS NOT NULL'):
            self.add_view(SessionReviewView(self,batch['batch_id']))
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
        try:
            mirror=GoogleNotebook.from_environment(self.db)
            if mirror:
                self.notebook_worker=asyncio.create_task(mirror.run(self))
        except Exception as error:
            log.error('Pep notebook setup failed: %s',type(error).__name__)

    async def work(self):
        await self.wait_until_ready()
        if self.coach and self.db.setting('tactical_ai_smoke:v1')!='passed':
            try:
                sample=await self.coach.advise('Synthetic connection test only: forced passes and vulnerability to counterattacks. Give one club coaching priority.','4-2-3-1')
                self.db.set_setting('tactical_ai_smoke:v1','passed')
                log.info('Tactical AI connection test passed; model=%s response_chars=%s',self.coach.model,len(sample))
            except Exception as error:
                log.error('Tactical AI connection test failed: %s',str(error) if isinstance(error,RuntimeError) else type(error).__name__)
        # One requested compatibility check; does not import or classify anything.
        if not self.db.setting('league_stats_check:v1'):
            try:
                check=await inspect_league_stats(self)
                self.db.set_setting('league_stats_check:v1',json.dumps(check))
                log.info('League stats channel check: %s',json.dumps(check['channels']))
                for recap in check['recaps']:
                    log.info('League stats public recap check: %s',json.dumps(recap))
                if not check['recaps']:
                    log.info('League stats check: no readable club bot recaps in the last 30 messages')
            except Exception as error:
                log.error('League stats check failed: %s',type(error).__name__)
        try:
            channel,_=self.recap_config()
            ignored=self.db.ignore_setup_prompts(channel,self.config.guild_id,self.config.owner_id)
            if ignored:
                log.info('Ignored %s historical OurProClubs setup prompts; raw records retained',len(ignored))
            await self.refresh_footers()
        except Exception as error:
            log.error('Existing footer refresh failed: %s',type(error).__name__)
        while not self.is_closed():
            try:
                try:
                    await asyncio.to_thread(daily_backup,self.db)
                except Exception as error:
                    log.error('Daily backup failed: %s',type(error).__name__)
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
        if self.notebook_worker:
            self.notebook_worker.cancel()
        if self.worker:
            self.worker.cancel()
        if self.media_runner:
            await self.media_runner.cleanup()
        await super().close()

    def recap_config(self):
        channel=int(self.db.setting('recap_channel',self.config.recap_channel_id))
        author=int(self.db.setting('recap_author',self.config.source_bot_id))
        return channel,author

    async def ingest_message(self,message):
        # Preserve existing records; automatic collection is paused.
        return

    async def recover_recaps(self):
        return

    async def pending_reviews(self, force=False):
        return False

    async def refresh_footers(self):
        owner=await self.fetch_user(self.config.owner_id)
        channel=owner.dm_channel or await owner.create_dm()
        ids={r['review_message_id'] for r in self.db.rows('SELECT review_message_id FROM matches WHERE review_message_id IS NOT NULL')}
        ids.update(r['message_id'] for r in self.db.rows('SELECT message_id FROM weekly_jobs WHERE message_id IS NOT NULL'))
        setup_ids={r['review_message_id'] for r in self.db.rows("SELECT review_message_id,raw_recap FROM matches WHERE match_type='Ignored' AND review_message_id IS NOT NULL") if is_setup_prompt(r['raw_recap'])}
        for message_id in ids:
            try:
                message=await channel.fetch_message(int(message_id))
                if message.author.id!=self.user.id:
                    continue
                changed=False
                archived=message_id in setup_ids
                for embed in message.embeds:
                    if archived and embed.description!='Ignored — this was an OurProClubs setup menu, not a match recap. No club statistics were counted.':
                        embed.description='Ignored — this was an OurProClubs setup menu, not a match recap. No club statistics were counted.'
                        changed=True
                    old=embed.footer.text if embed.footer else None
                    if old and not old.startswith(PEP_FOOTER+'\n'):
                        embed.set_footer(text=branded_footer(old));changed=True
                if changed or (archived and message.components):
                    if archived:
                        await message.edit(embeds=message.embeds,view=None)
                    else:
                        await message.edit(embeds=message.embeds)
            except discord.HTTPException:
                continue

    async def coaching_advice(self, user_id, request_id, analysis, formation=''):
        analysis=analysis.strip()
        if not analysis or len(analysis)>12000:
            raise ValueError('Paste PCT’s analysis as text, up to 12,000 characters.')
        async with self.coaching_lock:
            saved=self.db.one('SELECT advice FROM coaching_notes WHERE request_id=?',(str(request_id),))
            if saved:
                return saved['advice']
            provider='practical-library'
            if self.coach:
                try:
                    advice=await self.coach.advise(analysis,formation)
                    provider=self.coach.model
                except Exception as error:
                    log.error('Tactical AI unavailable: %s',str(error) if isinstance(error,RuntimeError) else type(error).__name__)
                    advice='AI coaching is temporarily unavailable. Here is general coaching guidance from Pep’s practical library:\n\n'+PracticalCoach().advise(analysis,formation)
            else:
                advice='AI coaching is not connected. General coaching guidance:\n\n'+PracticalCoach().advise(analysis,formation)
            self.db.execute('INSERT INTO coaching_notes(request_id,user_id,created_at,supplied_analysis,formation,advice,provider) VALUES (?,?,?,?,?,?,?)',
                (str(request_id),str(user_id),utcnow(),analysis,formation,advice,provider))
            return advice

    def coaching_embed(self, advice):
        embed=discord.Embed(title='PEP — TACTICAL ADVICE',description=advice[:3900])
        embed.set_footer(text=PEP_FOOTER)
        return embed

    async def on_message(self,message):
        if message.author.bot:
            return
        if message.guild is None:
            if message.author.id!=self.config.owner_id:
                return
            if not message.content.strip():
                await message.reply('Paste PCT’s written analysis as text. Screenshots and links alone are not read yet.',mention_author=False)
                return
            async with message.channel.typing():
                advice=await self.coaching_advice(message.author.id,message.id,message.content)
            kwargs={'embed':self.coaching_embed(advice),'mention_author':False}
            if len(advice)>3900:
                kwargs['file']=discord.File(io.BytesIO(advice.encode()),filename='pep-tactical-advice.txt')
            await message.reply(**kwargs)
            return
        if message.guild.id!=self.config.guild_id:
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
        lines=['Morning Coach. It’s time for your Birmingham City weekly recap. Paste this week’s verified NACL results and PCT findings when ready. Saved match selections remain available below.','Week: '+report['week_start'][:10]+' to '+report['week_end'][:10]+' (end exclusive).']
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

        @self.tree.command(name='tacticaladvice',description='Paste PCT analysis for private club tactical advice')
        @app_commands.check(authorized)
        @app_commands.describe(analysis='Paste PCT’s written findings and your observations',formation='Optional: the formation you used')
        async def tacticaladvice(interaction,analysis:str,formation:str=''):
            await interaction.response.defer(ephemeral=True)
            try:
                advice=await self.coaching_advice(interaction.user.id,interaction.id,analysis,formation)
            except ValueError as error:
                await interaction.followup.send(str(error),ephemeral=True); return
            kwargs={'embed':self.coaching_embed(advice),'ephemeral':True}
            if len(advice)>3900:
                kwargs['file']=discord.File(io.BytesIO(advice.encode()),filename='pep-tactical-advice.txt')
            await interaction.followup.send(**kwargs)

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

        @self.tree.command(name='notebook',description='Owner: download Pep’s Notebook for Excel or Google Sheets')
        @app_commands.check(authorized)
        async def export_notebook(interaction):
            if interaction.user.id!=self.config.owner_id:
                await interaction.response.send_message('Coach controls notebook downloads.',ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            try:
                data=await asyncio.to_thread(notebook,self.db)
                await interaction.followup.send('Pep’s Notebook — a snapshot of the central records:',
                    file=discord.File(io.BytesIO(data),filename='Peps_Notebook.zip'),ephemeral=True)
            except ValueError as error:
                await interaction.followup.send(str(error),ephemeral=True)

        @self.tree.command(name='backup',description='Owner: download a checked backup of Pep’s central database')
        @app_commands.check(authorized)
        async def backup_download(interaction):
            if interaction.user.id!=self.config.owner_id:
                await interaction.response.send_message('Only Coach can download the database.',ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            path=await asyncio.to_thread(daily_backup,self.db,refresh=True)
            if path.stat().st_size>7_500_000:
                await interaction.followup.send('Backup saved on Railway; it is too large for Discord.',ephemeral=True); return
            await interaction.followup.send('Private database backup. Keep a copy outside Railway.',file=discord.File(path),ephemeral=True)

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
            await interaction.response.send_message(f'Pep is online in tactical coaching mode. Automatic match imports and review DMs are paused. {unknown} saved Unknown matches remain. Friday reminders: {"enabled" if self.config.schedule_enabled else "test mode"}.',ephemeral=True)

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
            await interaction.response.send_message('Source settings saved. Automatic match imports are paused. Paste analysis into /tacticaladvice or DM Pep.',ephemeral=True)

        @self.tree.command(name='matches',description='List recent saved matches and their classifications')
        @app_commands.check(authorized)
        async def matches(interaction):
            rows=self.db.rows('SELECT * FROM matches ORDER BY played_at DESC,match_id DESC LIMIT 15')
            await interaction.response.send_message('\n'.join(f"#{m['match_id']} {match_label(m)} [{m['match_type']}]" for m in rows)[:1900] or 'No matches saved yet.',ephemeral=True)

        @self.tree.command(name='endsession',description='Management: finish this recap session and request one review DM')
        @app_commands.check(authorized)
        async def endsession(interaction):
            await interaction.response.defer(ephemeral=True)
            await self.recover_recaps()
            sent=await self.pending_reviews(force=True)
            await interaction.followup.send('Session review sent to Coach.' if sent else 'Automatic session reviews are paused. Use /tacticaladvice or DM Pep with PCT’s analysis.',ephemeral=True)

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
