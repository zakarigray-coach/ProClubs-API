"""Discord adapter: all football records live in the shared SQLite database."""
import asyncio
import aiohttp
import io
import json
import logging
import math
import os
from .recap_reset import reset_recap
from .report_verification import ReportHold, digest, validate_final
from .report_audit import assert_current
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
from .competitions import report_event, configure_report, set_match_details
from .parser import parse_recap, parse_registration, is_match_recap, is_setup_prompt
from .recap_check import readable_message, inspect_league_stats
from .reporter import Reporter, match_label
from .article_writer import SportsWriter, check_finished_prose, check_feature_quality, feature_facts
from .weekly_intake import save_submission, save_photo, content as report_content
from .scheduler import WeeklyScheduler, week_window
from .session_reviews import SessionReviews
from .tactical_coach import PracticalCoach
from .coaching_ai import OpenAICoach
from .recap_intake import RecapReader
from .excel_intake import read_excel
from .excel_stats import player_totals, save_excel_statistics, imported_statistics, stats_text, records
from .cup_setup import CupAvailabilityView, run_cup_setup, load as load_cup_setup

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
            min_values=0,max_values=len(matches),row=2 if kind=='Practice' and view.has_official else 1,
            options=[discord.SelectOption(label=f"#{m['match_id']} {match_label(m)}"[:100],value=str(m['match_id']),default=m['match_id'] in selected) for m in matches])

    async def callback(self, interaction):
        view=self.parent_view
        view.bot.db.replace_page_selection(view.report_id,self.page_ids,[int(v) for v in self.values])
        await interaction.response.edit_message(content=view.bot.report_summary(view.report_id),view=ReportView(view.bot,view.report_id,view.page))


async def report_attachments(db,report_id,article):
    from .article_layout import media_pages
    from .recap_output import checked_outputs
    payload,text=await asyncio.to_thread(checked_outputs,db,report_id)
    pages=await asyncio.to_thread(media_pages,db,report_id)
    files=[discord.File(io.BytesIO(data),filename=f'RT_Media_{report_id}_{i+1}.png') for i,data in enumerate(pages)]
    files.append(discord.File(io.BytesIO(text.encode()),filename=f'RT_Report_{report_id}.txt'))
    files.append(discord.File(io.BytesIO(json.dumps(payload,ensure_ascii=False,indent=2).encode()),filename=f'RT_Cover_{report_id}.json'))
    return files


async def send_article_text(target,article):
    from .recap_output import discord_chunks
    for chunk in discord_chunks(article):
        await target.send(chunk,allowed_mentions=discord.AllowedMentions.none())


async def send_checked_article(target,db,report_id,sample=False):
    from .recap_output import checked_outputs
    payload,article=await asyncio.to_thread(checked_outputs,db,report_id,sample)
    await send_article_text(target,article)


def player_photo_button(bot,report_id,context):
    async def request_photo(interaction):
        if interaction.user.id!=bot.config.owner_id:
            await interaction.response.send_message('Only Coach can attach the player photo.',ephemeral=True); return
        bot.db.set_setting('weekly_photo_awaiting',str(report_id))
        await interaction.response.send_message('Send the selected featured-player photo in this DM (PNG, JPEG or WebP, up to 8 MB). This photo will accompany the draft. Say cancel photo to cancel.',ephemeral=True)
    return Action('Attach Player Photo',f'pep:playerphoto:{context}:{report_id}',request_photo)


class RecapConfirmView(ManagedView):
    def __init__(self,bot,report_id,request_id):
        super().__init__(bot)
        async def confirm(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can confirm these results.',ephemeral=True); return
            async with bot.coaching_lock:
                saved=json.loads(bot.db.setting(f'recap_preview:{request_id}','{}'))
                if not saved or saved.get('used'):
                    await interaction.response.send_message('This preview has already been used. Send your recap again to change it.',ephemeral=True); return
                try:
                    existing=report_content(bot.db,report_id)
                    assert_recap_lines(bot.db,report_id,saved['lines'])
                    save_submission(bot.db,report_id,interaction.user.id,bot.config.guild_id,'\n'.join(saved['lines']),existing.get('notes',''),saved.get('player_name') or existing.get('player_name',''),saved.get('player_evidence') or existing.get('player_evidence',''))
                    matches=bot.db.period_matches(bot.db.report(report_id)['week_start'],bot.db.report(report_id)['week_end'],True)
                    wanted=set(saved['lines'])
                    ids=[m['match_id'] for m in matches if m['raw_recap'] in wanted]
                    workbook=saved.get('excel_source') or bot.db.setting(f'weekly_excel:{report_id}','')
                    if workbook:
                        save_excel_statistics(bot.db,workbook,[m for m in matches if m['match_id'] in ids])
                    bot.db.replace_page_selection(report_id,[m['match_id'] for m in matches],ids)
                    assert_recap_scope(bot.db,report_id)
                    bot.db.confirm_report(report_id)
                except ValueError as error:
                    await interaction.response.send_message(str(error),ephemeral=True); return
                saved['used']=True;bot.db.set_setting(f'recap_preview:{request_id}',json.dumps(saved))
                await interaction.response.defer(ephemeral=True)
                try:
                    article=await asyncio.to_thread(bot.reporter.generate,report_id)
                    files=await report_attachments(bot.db,report_id,article)
                except ReportHold as error:
                    saved['used']=False;bot.db.set_setting(f'recap_preview:{request_id}',json.dumps(saved))
                    await interaction.followup.send(str(error),ephemeral=True)
                    return
                except (RuntimeError,ValueError,aiohttp.ClientError,asyncio.TimeoutError):
                    saved['used']=False;bot.db.set_setting(f'recap_preview:{request_id}',json.dumps(saved))
                    log.warning('Weekly sports writer unavailable; confirmed facts retained.')
                    await interaction.followup.send('The sports writer could not finish. Your results are saved. Tap Confirm Results & Draft again to retry.',ephemeral=True)
                    return
                owner=await bot.fetch_user(bot.config.owner_id)
                if existing.get('photo'):
                    files.append(discord.File(io.BytesIO(existing['photo']),filename=f'Featured_Player_{report_id}.{existing["photo_extension"]}'))
                await owner.send(content=f'Weekly draft #{report_id} — review only. Nothing published.',files=files,view=DraftView(bot,report_id),allowed_mentions=discord.AllowedMentions.none())
                await send_checked_article(owner,bot.db,report_id)
                bot.db.execute('UPDATE weekly_reports SET draft_sent_at=? WHERE report_id=?',(utcnow(),report_id))
                bot.db.set_setting('weekly_dm_awaiting','')
                bot.db.set_setting(f'weekly_excel:{report_id}','')
                bot.db.set_setting(f'weekly_excel_context:{report_id}','')
                await interaction.followup.send('Your private article draft is ready.',ephemeral=True)
        self.add_item(Action('Confirm Results & Draft',f'pep:recapconfirm:{request_id}',confirm,discord.ButtonStyle.success))
        async def change(interaction):
            bot.db.set_setting('weekly_dm_awaiting',str(report_id))
            await interaction.response.send_message('Reply to Pep with the corrected recap text or photo. No new results have been saved by this button.',ephemeral=True)
        self.add_item(Action('Send Corrections',f'pep:recapcorrect:{request_id}',change))
        async def setup(interaction):
            await interaction.response.send_message(bot.report_summary(report_id),view=ReportView(bot,report_id),ephemeral=True)
        self.add_item(player_photo_button(bot,report_id,f'preview:{request_id}'))
        self.add_item(Action('Choose Matches / Report Details',f'pep:recapsetup:{request_id}',setup))


class WeeklyFactsModal(discord.ui.Modal, title='Weekly results and article notes'):
    results=discord.ui.TextInput(label='Results: date | type | opponent | score', style=discord.TextStyle.paragraph, required=False, placeholder='2026-10-15 | Official Home | Chelsea | 3-1', max_length=3000)
    notes=discord.ui.TextInput(label='Verified PCT findings / club notes (optional)', style=discord.TextStyle.paragraph, required=False, max_length=3000)
    player=discord.ui.TextInput(label='Player of the Week name or mention (optional)', required=False, max_length=100)
    evidence=discord.ui.TextInput(label='Their verified achievement (optional)', required=False, max_length=500)

    def __init__(self, bot, report_id):
        super().__init__()
        self.bot=bot; self.report_id=report_id
        existing=report_content(bot.db,report_id)
        self.notes.default=existing.get('notes','')
        event=report_event(bot.db,report_id)
        if event and event['report_type']=='Cup':
            self.player.label='Cup Standout name (optional)'
            self.results.placeholder='2026-10-13 | Cup | Opponent | 3-1'
        self.player.default=existing.get('player_name','')
        self.evidence.default=existing.get('player_evidence','')

    async def on_submit(self, interaction):
        try:
            assert_recap_lines(self.bot.db,self.report_id,[line for line in str(self.results).splitlines() if line.strip()])
            count=save_submission(self.bot.db,self.report_id,interaction.user.id,self.bot.config.guild_id,str(self.results),str(self.notes),str(self.player),str(self.evidence))
        except ValueError as error:
            await interaction.response.send_message(str(error),ephemeral=True); return
        await interaction.response.send_message(f'Saved {count} new results. Choose the matches below, then Generate Report.\n'+self.bot.report_summary(self.report_id),view=ReportView(self.bot,self.report_id),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class CupEventModal(discord.ui.Modal,title='Cup competition setup'):
    name=discord.ui.TextInput(label='Competition name',max_length=160)
    dates=discord.ui.TextInput(label='Event dates: start to end (YYYY-MM-DD)',max_length=30)
    format_text=discord.ui.TextInput(label='Confirmed format (optional)',required=False,max_length=1000,style=discord.TextStyle.paragraph)
    outcome=discord.ui.TextInput(label='Confirmed outcome (or Unknown)',default='Unknown',placeholder='Advanced / Eliminated / Champions / Still competing',max_length=30)
    evidence=discord.ui.TextInput(label='Outcome confirmation / source (optional)',required=False,max_length=1000,style=discord.TextStyle.paragraph)

    def __init__(self,bot,report_id):
        super().__init__();self.bot=bot;self.report_id=report_id
        event=report_event(bot.db,report_id)
        if event:
            self.name.default=event['name'];self.dates.default=(event['event_start'] or '')+' to '+(event['event_end'] or '')
            self.format_text.default=event['format'] or '';self.outcome.default=event['outcome'];self.evidence.default=event['outcome_evidence'] or ''

    async def on_submit(self,interaction):
        if interaction.user.id!=self.bot.config.owner_id:
            await interaction.response.send_message('Only Coach can confirm cup reporting details.',ephemeral=True);return
        try:
            from datetime import date
            dates=str(self.dates).split(' to ')
            a=date.fromisoformat(dates[0]);b=date.fromisoformat(dates[-1])
            if b<a:raise ValueError('End date must not precede the start.')
            key='cup:'+digest({'name':str(self.name),'start':a.isoformat()})[:20]
            existing=report_event(self.bot.db,self.report_id)
            if existing and existing['name']==str(self.name) and existing['event_start']==a.isoformat():key=existing['competition_key']
            self.bot.db.execute('''INSERT INTO competitions(competition_key,name,report_type,event_start,event_end,format) VALUES (?,?,'Cup',?,?,?)
                ON CONFLICT(competition_key) DO UPDATE SET name=excluded.name,event_start=excluded.event_start,event_end=excluded.event_end,format=excluded.format''',
                (key,str(self.name),a.isoformat(),b.isoformat(),str(self.format_text) or None))
            from .scheduler import ET
            start=datetime.combine(a,datetime.min.time(),ET).astimezone(timezone.utc).isoformat()
            end=(datetime.combine(b,datetime.min.time(),ET)+timedelta(days=1)).astimezone(timezone.utc).isoformat()
            report=self.bot.db.open_report(start,end,interaction.user.id,key)
            self.report_id=report['report_id']
            configure_report(self.bot.db,self.report_id,key,str(self.outcome).strip(),str(self.evidence) or None)
            self.bot.db.set_setting('weekly_dm_awaiting',str(self.report_id))
        except ValueError as error:
            await interaction.response.send_message(str(error),ephemeral=True);return
        await interaction.response.send_message(self.bot.report_summary(self.report_id),view=ReportView(self.bot,self.report_id),ephemeral=True)


class CupAwardModal(discord.ui.Modal,title='Cup featured-player recognition'):
    label=discord.ui.TextInput(label='Cup Standout or Player of the Tournament',default='Cup Standout',max_length=30)
    scope=discord.ui.TextInput(label='Who confirmed the award, and its scope?',required=False,style=discord.TextStyle.paragraph,max_length=1000)

    def __init__(self,bot,report_id):
        super().__init__();self.bot=bot;self.report_id=report_id

    async def on_submit(self,interaction):
        if interaction.user.id!=self.bot.config.owner_id:
            await interaction.response.send_message('Only Coach can confirm cup reporting details.',ephemeral=True);return
        event=report_event(self.bot.db,self.report_id)
        try:
            configure_report(self.bot.db,self.report_id,event['competition_key'],event['outcome'],event['outcome_evidence'],str(self.label),str(self.scope) or None)
        except (ValueError,TypeError) as error:
            await interaction.response.send_message(str(error),ephemeral=True);return
        await interaction.response.send_message('Recognition saved. Use Add Results / Notes to select the player and their verified achievement.',ephemeral=True)


class CupMatchModal(discord.ui.Modal,title='Cup fixture details — unknown is fine'):
    match_id=discord.ui.TextInput(label='Match ID',max_length=20)
    stage=discord.ui.TextInput(label='Stage | Group / bracket (optional)',required=False,placeholder='Quarter-final | Bracket A',max_length=200)
    tie=discord.ui.TextInput(label='Two-leg tie ID | Leg 1 or 2 (optional)',required=False,max_length=100)
    scores=discord.ui.TextInput(label='Extra-time final score | Shootout (optional)',required=False,placeholder='2-2 | 5-4 (Birmingham first; unknown is blank)',max_length=60)
    evidence=discord.ui.TextInput(label='Source / explicit management confirmation',default='Confirmed by management',max_length=1000)

    def __init__(self,bot,report_id):
        super().__init__();self.bot=bot;self.report_id=report_id

    async def on_submit(self,interaction):
        if interaction.user.id!=self.bot.config.owner_id:
            await interaction.response.send_message('Only Coach can confirm cup reporting details.',ephemeral=True);return
        try:
            import re
            event=report_event(self.bot.db,self.report_id)
            if not event or event['report_type']!='Cup':raise ValueError('Start this cup with /cupreport first.')
            mid=int(str(self.match_id));match=self.bot.db.match(mid);report=self.bot.db.report(self.report_id)
            if not match or not report['week_start']<=match['played_at']<report['week_end']:raise ValueError('Choose a match in this reporting period.')
            stage=(str(self.stage).split('|')+[''])[:2];tie=(str(self.tie).split('|')+[''])[:2]
            values={'stage':stage[0].strip() or None,'group_bracket':stage[1].strip() or None,'tie_key':tie[0].strip() or None,'leg':int(tie[1]) if tie[1].strip() else None}
            for raw,prefix in zip((str(self.scores).split('|')+[''])[:2],('extra_time','penalties')):
                if raw.strip():
                    score=re.fullmatch(r'\s*(\d+)\s*[-–]\s*(\d+)\s*',raw)
                    if not score:raise ValueError('Use Birmingham-first scores such as 2-2, leaving unknown blank.')
                    values[prefix+'_for'],values[prefix+'_against']=map(int,score.groups())
            set_match_details(self.bot.db,mid,event['competition_key'],interaction.user.id,str(self.evidence),**values)
        except (ValueError,TypeError) as error:
            await interaction.response.send_message(str(error),ephemeral=True);return
        await interaction.response.send_message('Cup details saved. This fixture stays out of MPL league totals.\n'+self.bot.report_summary(self.report_id),view=ReportView(self.bot,self.report_id),ephemeral=True)


def eligible_recap_matches(db,report_id):
    report=db.report(report_id);event=report_event(db,report_id)
    cup=event and event['report_type']=='Cup'
    rows=db.period_matches(report['week_start'],report['week_end'],True)
    if cup:return [m for m in rows if m['match_type']=='Cup' and m['competition']==event['name']]
    return [m for m in rows if m['match_type']=='Official' and (not m['competition'] or 'MPL' in m['competition'].upper())]


def assert_recap_scope(db,report_id):
    allowed={m['match_id'] for m in eligible_recap_matches(db,report_id)}
    selected=db.selected(report_id)
    if not selected or any(m['match_id'] not in allowed for m in selected):
        raise ValueError('Choose eligible MPL or selected-cup matches. Practice, scrim and test records stay saved but are excluded from new articles.')


def assert_recap_lines(db,report_id,lines):
    event=report_event(db,report_id);cup=event and event['report_type']=='Cup'
    for line in lines:
        parts=line.split('|');kind=parts[1].strip() if len(parts)==4 else ''
        if (cup and kind not in ('Cup','Cup Home','Cup Away')) or (not cup and kind not in ('Official Home','Official Away')):
            raise ValueError('This report accepts only '+('cup matches' if cup else 'official MPL matches')+'. Practices, scrims and tests will not be included.')


class ReportView(ManagedView):
    def __init__(self, bot, report_id, page=0):
        super().__init__(bot)
        self.report_id=report_id; self.page=page
        report=bot.db.report(report_id)
        if not report or report['status'] in ('skipped','approved'):
            return
        event=report_event(bot.db,report_id)
        eligible=bot.db.period_matches(report['week_start'],report['week_end'],True)
        if event:
            kind='Cup' if event['report_type']=='Cup' else 'Official'
            eligible=[m for m in eligible if m['match_type']==kind and (kind!='Cup' or m['competition']==event['name'])]
        else:
            eligible=[m for m in eligible if m['match_type']=='Official' and (not m['competition'] or 'MPL' in m['competition'].upper())]
        # 20 per page keeps both menus under Discord's 25-option limit.
        total=max(1,(len(eligible)+19)//20)
        self.page=min(max(page,0),total-1)
        page_matches=eligible[self.page*20:(self.page+1)*20]
        self.has_official=any(m['match_type']=='Official' for m in page_matches)
        selected={m['match_id'] for m in bot.db.selected(report_id)}
        for kind in ('Official','Cup'):
            rows=[m for m in page_matches if m['match_type']==kind]
            if rows:
                self.add_item(MatchSelect(self,rows,kind,selected))
        action_row=2
        async def generate(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Coach must confirm the article selections.',ephemeral=True); return
            try:
                assert_recap_scope(bot.db,report_id)
                bot.db.confirm_report(report_id)
            except ValueError as error:
                await interaction.response.send_message(str(error),ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            try:
                article=await asyncio.to_thread(bot.reporter.generate,report_id)
                files=await report_attachments(bot.db,report_id,article)
            except ReportHold as error:
                await interaction.followup.send(str(error),ephemeral=True)
                return
            except (RuntimeError,ValueError,aiohttp.ClientError,asyncio.TimeoutError):
                log.warning('Weekly sports writer unavailable; confirmed selections retained.')
                await interaction.followup.send('The draft could not be completed. Your selections are saved. Try Generate Report again.',ephemeral=True)
                return
            owner=await bot.fetch_user(bot.config.owner_id)
            supplied=report_content(bot.db,report_id)
            if supplied.get('photo'):
                files.append(discord.File(io.BytesIO(supplied['photo']),filename=f'Featured_Player_{report_id}.{supplied["photo_extension"]}'))
            await owner.send(content=f'RT Football Media draft #{report_id} — review only. Nothing has been published.',
                files=files,view=DraftView(bot,report_id),allowed_mentions=discord.AllowedMentions.none())
            await send_checked_article(owner,bot.db,report_id)
            bot.db.execute('UPDATE weekly_reports SET draft_sent_at=? WHERE report_id=?',(utcnow(),report_id))
            await interaction.followup.send('Draft sent to Coach for review.',ephemeral=True)
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
        async def add_facts(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can submit weekly facts.',ephemeral=True); return
            await interaction.response.send_modal(WeeklyFactsModal(bot,report_id))
        async def event_setup(interaction):
            await interaction.response.send_modal(CupEventModal(bot,report_id))
        async def cup_match(interaction):
            await interaction.response.send_modal(CupMatchModal(bot,report_id))
        async def cup_award(interaction):
            await interaction.response.send_modal(CupAwardModal(bot,report_id))
        if event and event['report_type']=='Cup':
            self.add_item(Action('Cup Award Scope',f'pep:cupaward:{report_id}',cup_award,row=4))
            self.add_item(Action('Cup Competition Details',f'pep:cupevent:{report_id}',event_setup,row=4))
            self.add_item(Action('Classify / Edit Cup Match',f'pep:cupmatch:{report_id}',cup_match,row=4))
        self.add_item(Action('Add Results / Notes',f'pep:facts:{report_id}',add_facts,row=4))
        self.add_item(Action('Generate Report',f'gaffer:generate:{report_id}',generate,discord.ButtonStyle.primary,row=action_row))
        self.add_item(Action('Review Unknown Matches',f'gaffer:unknown:{report_id}',review,row=action_row))
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
            try:
                with bot.db.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    audit=conn.execute("SELECT fact_sheet,article_hash FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,)).fetchone()
                    if audit:
                        saved=conn.execute('SELECT title,article FROM weekly_reports WHERE report_id=?',(report_id,)).fetchone()
                        if not saved['article'] or digest({'title':saved['title'],'body':saved['article'].split('\n\n',1)[1].strip()})!=audit['article_hash']:
                            raise ReportHold('This draft changed after verification. Generate a fresh checked article before approval.')
                        assert_current(bot.db,report_id,json.loads(audit['fact_sheet']))
                    cur=conn.execute("UPDATE weekly_reports SET status='approved' WHERE report_id=? AND status='draft'",(report_id,))
            except ReportHold as error:
                await interaction.response.send_message(str(error),ephemeral=True);return
            await interaction.response.send_message('Approved and saved. Nothing was published.' if cur.rowcount else 'This draft has changed. Generate a fresh draft.',ephemeral=True)
        async def change(interaction):
            if bot.db.report(report_id)['status']=='skipped':
                await interaction.response.send_message('This week was skipped.',ephemeral=True); return
            bot.db.execute("UPDATE weekly_reports SET status='selecting',article=NULL,observations=NULL WHERE report_id=?",(report_id,))
            await interaction.response.send_message(bot.report_summary(report_id),view=ReportView(bot,report_id),ephemeral=True)
        async def statistics(interaction):
            audits=bot.db.rows("SELECT fact_sheet FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
            if not audits:
                await interaction.response.send_message('Generate a checked draft first.',ephemeral=True);return
            sheet=json.loads(audits[0]['fact_sheet'])
            sections=[]
            for kind,group in sheet['groups'].items():
                sections.append(kind.upper()+' MATCHES\n'+stats_text(group['players']))
            if sheet['warnings']:sections.append('DATA COVERAGE\n'+'\n'.join(sheet['warnings']))
            await interaction.response.send_message(file=discord.File(io.BytesIO(('\n\n'.join(sections)).encode()),filename=f'RT_Statistics_{report_id}.txt'),ephemeral=True)
        self.add_item(Action('View Statistics',f'pep:statistics:{report_id}',statistics))
        self.add_item(player_photo_button(bot,report_id,'draft'))
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
        self.bot.db.set_setting('weekly_dm_awaiting',str(report_id))
        return message.id


class GafferBot(discord.Client):
    def __init__(self, config):
        intents=discord.Intents.default(); intents.message_content=True
        super().__init__(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        self.config=config; self.db=Database(config.database_path)
        self.cup_availability_lock=asyncio.Lock()
        reset_request=os.getenv('PEP_RECAP_RESET_REQUEST','')
        if reset_request:
            report_id,request=reset_request.split(':',1)
            if reset_recap(self.db,int(report_id),config.owner_id,request):
                log.info('Owner-requested recap reset completed; report=%s',report_id)
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
        self.recap_reader=RecapReader(self.coach) if self.coach else None
        self.reporter=Reporter(self.db,writer=SportsWriter(self.coach.key,os.getenv("PEP_REPORTER_MODEL",self.coach.model)) if self.coach else None)
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
        cup_setup=load_cup_setup(self.db)
        if cup_setup.get('starter_message_id'):
            self.add_view(CupAvailabilityView(self.db,self.cup_availability_lock),message_id=cup_setup['starter_message_id'])
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
        for row in self.db.rows("SELECT key,value FROM settings WHERE key LIKE 'recap_preview:%'"):
            saved=json.loads(row['value'])
            if not saved.get('used'):
                self.add_view(RecapConfirmView(self,saved['report_id'],row['key'].split(':',1)[1]))
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
        if self.recap_reader and self.db.setting('recap_reader_smoke:v1')!='passed':
            try:
                check=await self.recap_reader.extract('Synthetic connectivity test: 2026-10-15, Official Home, Birmingham City 3-1 Chelsea.',[],['2026-10-12','2026-10-19'])
                if len(check['lines'])!=1 or check['questions']:
                    raise ValueError('Recap reader could not extract test facts')
                self.db.set_setting('recap_reader_smoke:v1','passed')
                log.info('Weekly recap reader connection verified; no match data imported')
            except Exception as error:
                log.error('Weekly recap reader check failed: %s',str(error) if isinstance(error,RuntimeError) else type(error).__name__)
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
        await run_cup_setup(self)
        request=os.getenv('PEP_REPORT_REWRITE_REQUEST','')
        if request and not getattr(self,'rewrite_running',False) and not self.db.setting('report_rewrite:'+request):
            self.rewrite_running=True
            asyncio.create_task(self.rewrite_verified_report(request))

    async def rewrite_verified_report(self,request):
        try:
            report_id=int(request.split(':',1)[0])
            if request.endswith(':inspect'):
                audits=self.db.rows("SELECT state,source_hash,attempts,error FROM report_generation_audit WHERE report_id=? ORDER BY audit_id DESC LIMIT 1",(report_id,))
                log.info('Owner-requested held article diagnostics: %s',json.dumps(audits,ensure_ascii=False))
                self.db.set_setting('report_rewrite:'+request,'complete')
                return
            selected=self.db.selected(report_id)
            if len(selected)!=4:raise ValueError('Four-match test requires exactly four selections.')
            stats=self.db.rows('SELECT s.* FROM match_statistics s JOIN report_matches r USING(match_id) WHERE r.report_id=?',(report_id,))
            diagnostic=player_totals(stats)
            for player in diagnostic:
                if player['player'] in ('DaddyGray10420','TraapxLit'):
                    log.info('Four-match fact audit: player=%s dribbles=%s appearances=%s',player['player'],player.get('dribbles_completed'),player['appearances'])
            if request.endswith(':recheck'):
                from .recheck_article import ReviewedDraftRecheck
                self.db.confirm_report(report_id)
                article=await asyncio.to_thread(Reporter(self.db,writer=ReviewedDraftRecheck(self.db,report_id)).generate,report_id)
            elif request.endswith((':deliver',':savedpreview',':sampledeliver')):
                saved=self.db.report(report_id)
                if saved['status'] not in ('draft','confirmed') or not saved['article']:raise ValueError('No reviewed draft available.')
                article=saved['article']
                audits=self.db.rows("SELECT * FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
                checked={'title':saved['title'],'body':article.split('\n\n',1)[1].strip()}
                if not audits or audits[0]['article_hash']!=digest(checked):
                    raise ValueError('Saved draft has no matching completed verification. Generate it through the reporting workflow first.')
                sheet=json.loads(audits[0]['fact_sheet'])
                assert_current(self.db,report_id,sheet)
                proof=json.loads(audits[0]['verification'])
                validate_final(checked,sheet,proof['evidence'])
                check_feature_quality(checked,{'management':report_content(self.db,report_id),'observations':{'player_statistics':{kind:group['players'] for kind,group in sheet['groups'].items()}}})
                if saved['status']=='confirmed':
                    self.db.execute("UPDATE weekly_reports SET status='draft' WHERE report_id=? AND status='confirmed' AND article=?",(report_id,article))

            else:
                self.db.confirm_report(report_id)
                article=await asyncio.to_thread(self.reporter.generate,report_id)
            if request.endswith((':preview',':savedpreview')):
                audit=self.db.one("SELECT fact_sheet,verification FROM report_generation_audit WHERE report_id=? AND state='passed' ORDER BY audit_id DESC LIMIT 1",(report_id,))
                if not audit:raise ValueError('No completed verification record is available for this draft.')
                sheet=json.loads(audit['fact_sheet'])
                persisted_proof=json.loads(audit['verification'])
                log.info('Owner-requested editorial preview: %s',json.dumps({'article':article,'sources':{'source_hash':sheet['source_hash'],'fixtures':sheet['fixtures'],'groups':sheet['groups'],'warnings':sheet['warnings']},'verification':persisted_proof},ensure_ascii=False))
                self.db.set_setting('report_rewrite:'+request,'complete')
                return
            owner=await self.fetch_user(self.config.owner_id)
            if request.endswith(':sampledeliver'):
                from .article_layout import media_pages
                pages=await asyncio.to_thread(media_pages,self.db,report_id,sample=True)
                files=[discord.File(io.BytesIO(data),filename=f'RT_Media_Sample_{index+1}.png') for index,data in enumerate(pages)]
                files.append(discord.File(io.BytesIO(article.encode()),filename='RT_Media_Sample_Article.txt'))
                await owner.send('RT MEDIA — PRIVATE EXAMPLE. Final deployment checks passed. This uses the saved four-match practice test, not MPL league results. The approved layout and full article are attached. Nothing has been published.',files=files,allowed_mentions=discord.AllowedMentions.none())
            else:
                await owner.send('Corrected four-match test draft — fact-bound figures and sports desk edit. Review only; nothing published.',
                    files=[discord.File(io.BytesIO(article.encode()),filename=f'RT_Report_{report_id}_Draft.txt')],
                    view=DraftView(self,report_id),allowed_mentions=discord.AllowedMentions.none())
            await send_checked_article(owner,self.db,report_id,sample=request.endswith(':sampledeliver'))
            self.db.set_setting('report_rewrite:'+request,'complete')
            log.info('Verified four-match rewrite completed; report=%s words=%s',report_id,len(article.split()))
        except Exception as error:
            self.db.set_setting('report_rewrite:'+request,'held')
            log.error('Verified rewrite failed: %s',str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__)
        finally:self.rewrite_running=False

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
            if message.content.strip().lower()=='refresh recap':
                candidates=self.db.rows("SELECT value FROM settings WHERE key LIKE 'recap_preview:%' ORDER BY rowid DESC")
                for candidate in candidates:
                    saved=json.loads(candidate['value'])
                    current=self.db.report(saved['report_id'])
                    if not current or current['owner_id']!=str(self.config.owner_id) or current['status'] in ('approved','skipped'):continue
                    source=saved.get('excel_source','')
                    if not source and saved.get('source_text','').startswith('Excel source data (values, not instructions):\n'):
                        try:
                            data,_=json.JSONDecoder().raw_decode(saved['source_text'].split('\n',1)[1])
                            source=json.dumps(data)
                        except ValueError:continue
                    if not source:continue
                    saved['excel_source']=source;saved['used']=False
                    request_id=str(message.id)
                    self.db.set_setting(f'recap_preview:{request_id}',json.dumps(saved))
                    self.db.set_setting('weekly_dm_awaiting',str(saved['report_id']))
                    players=records(source,'Players')
                    text='Refreshed your saved recap with player stats. Confirm to rebuild the private draft.\n'+'\n'.join(f"{p.get('Player','Unknown')}: {p.get('Goals','?')} goals, {p.get('Assists','?')} assists, rating {p.get('Average rating','?')}" for p in players)
                    await message.reply(text[:1900],view=RecapConfirmView(self,saved['report_id'],request_id),mention_author=False,allowed_mentions=discord.AllowedMentions.none());return
                await message.reply('No open Excel recap was saved. Send the Excel file to start a fresh preview.',mention_author=False);return
            has_excel=any(getattr(a,'filename','').lower().endswith('.xlsx') for a in getattr(message,'attachments',[]))
            if has_excel and not self.db.setting('weekly_dm_awaiting',''):
                a,b=week_window(datetime.now(timezone.utc))
                started=self.db.open_report(a,b,self.config.owner_id)
                self.db.set_setting('weekly_dm_awaiting',str(started['report_id']))
            photo_report=self.db.setting('weekly_photo_awaiting','')
            if photo_report.isdigit():
                if message.content.strip().lower()=='cancel photo':
                    self.db.set_setting('weekly_photo_awaiting','')
                    await message.reply('Photo attachment cancelled.',mention_author=False); return
                if getattr(message,'attachments',[]) and not has_excel:
                    await self.attach_weekly_photo(message,int(photo_report));return
            if message.content.strip().lower() in ('weekly recap','weekly report','prepare weekly recap'):
                a,b=week_window(datetime.now(timezone.utc))
                report=self.db.open_report(a,b,self.config.owner_id)
                self.db.set_setting('weekly_dm_awaiting',str(report['report_id']))
                await message.reply('Send this week’s league recap text or photo, with dates and home/away. I’ll check the results with you, then prepare a private draft.',mention_author=False); return
            pending=self.db.setting('weekly_dm_awaiting','')
            report=self.db.report(int(pending)) if pending.isdigit() else None
            if report and report['status'] not in ('approved','skipped') and not message.content.lower().startswith(('tactics:', 'coaching:')):
                await self.read_weekly_dm(message,report)
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

    async def attach_weekly_photo(self,message,report_id):
        attachment=message.attachments[0]
        if attachment.size>8*1024*1024:
            await message.reply('Photo must be 8 MB or smaller.',mention_author=False); return
        try:
            report=self.db.report(report_id)
            was_draft=report and report['status']=='draft'
            save_photo(self.db,report_id,message.author.id,await attachment.read())
            self.db.set_setting('weekly_photo_awaiting','')
            if was_draft:
                article=self.db.report(report_id)['article']
                files=await report_attachments(self.db,report_id,article)
                saved=report_content(self.db,report_id)
                await message.reply(f'Updated private draft #{report_id} with your selected player photo. Nothing published.',files=files,view=DraftView(self,report_id),mention_author=False,allowed_mentions=discord.AllowedMentions.none())
                await send_checked_article(message.channel,self.db,report_id)
            else:
                await message.reply('Player photo saved. Tap Confirm Results & Draft on the recap preview to include it with your article.',mention_author=False)
        except (ValueError,RuntimeError,aiohttp.ClientError) as error:
            await message.reply('Could not attach that photo. '+(str(error) if isinstance(error,ValueError) else 'Please try again.'),mention_author=False)

    async def read_weekly_dm(self,message,report):
        if not self.recap_reader:
            await message.reply('Photo/text reading is unavailable. Use Add Results / Notes for now; your recap has not been imported.',mention_author=False); return
        request_id=str(message.id)
        if self.db.setting(f'recap_preview:{request_id}'):
            await message.reply('This recap already has a result preview below.',mention_author=False); return
        images=[]
        supplied=message.content
        cached=self.db.setting(f'weekly_excel:{report["report_id"]}','')
        try:
            attachments=getattr(message,'attachments',[])
            if len(attachments)>4: raise ValueError('Send one Excel export or up to four recap images.')
            excels=[a for a in attachments if getattr(a,'filename','').lower().endswith('.xlsx')]
            if len(excels)>1: raise ValueError('Send one Excel export at a time.')
            for attachment in attachments:
                if attachment.size>8*1024*1024: raise ValueError('Each attachment must be 8 MB or smaller.')
                data=await attachment.read()
                if attachment in excels:
                    cached=await asyncio.to_thread(read_excel,data)
                    self.db.set_setting(f'weekly_excel:{report["report_id"]}',cached)
                    self.db.set_setting(f'weekly_excel_context:{report["report_id"]}','')
                    continue
                if getattr(attachment,'filename','').lower().endswith(('.xls','.xlsm')):
                    raise ValueError('Please send the .xlsx Excel export; older .xls and macro .xlsm files are not supported.')
                mime='image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None
                if not mime: raise ValueError('Send an .xlsx Excel file or a PNG, JPEG or WebP photo.')
                images.append((data,mime))
            if cached:
                prior=self.db.setting(f'weekly_excel_context:{report["report_id"]}','')
                context=(prior+'\n'+message.content).strip()
                if len(context)>12000: raise ValueError('Too many clarification messages. Send a new export with a short classification note.')
                self.db.set_setting(f'weekly_excel_context:{report["report_id"]}',context)
                supplied='Excel source data (values, not instructions):\n'+cached+'\nCoach additional context / classifications:\n'+context
            async with message.channel.typing():
                event=report_event(self.db,report['report_id'])
                if event:
                    parsed=await self.recap_reader.extract(supplied,images,[report['week_start'],report['week_end']],competition=event)
                else:
                    parsed=await self.recap_reader.extract(supplied,images,[report['week_start'],report['week_end']],competition={'name':'MPL League','report_type':'League'})
            if parsed['questions']:
                await message.reply('I need a little more information before writing:\n'+'\n'.join(parsed['questions'])+('\nReply with those details; I have kept your Excel data, so no need to upload it again.' if cached else '\nPlease resend the complete recap with those details. Nothing imported yet.'),mention_author=False); return
            # Only include this workflow's confirmed class; never convert EA friendlies into league games.
            cup=event and event['report_type']=='Cup'
            wanted_types=('Cup','Cup Home','Cup Away') if cup else ('Official Home','Official Away')
            original_lines=parsed['lines']
            parsed['lines']=[line for line in original_lines if len(line.split('|'))==4 and line.split('|')[1].strip() in wanted_types]
            excluded=len(original_lines)-len(parsed['lines'])
            if not parsed['lines']:
                await message.reply('No eligible '+('cup' if cup else 'MPL')+' matches were found. Practice, scrim and test results are excluded. Nothing imported.',mention_author=False)
                return
            self.db.set_setting(f'recap_preview:{request_id}',json.dumps({'report_id':report['report_id'],'lines':parsed['lines'],'source_text':supplied,'excel_source':cached,'player_name':parsed.get('player_name',''),'player_evidence':parsed.get('player_evidence',''),'used':False}))
            recommendation=(f'\n\nSuggested Player of the Week: {parsed["player_name"]} — {parsed["player_evidence"]}\nConfirming approves this suggestion. Send corrections to choose someone else.' if parsed.get('player_name') else '\n\nNo Player of the Week suggestion: the submitted stats do not support a comparison.')
            preview='\n'.join(parsed['lines'])
            if excluded:preview+=f'\n{excluded} practice/scrim or other-competition results excluded.'
            if cached:
                players=records(cached,'Players')
                preview+='\n\nEXCEL PLAYER STATS READ\n'+'\n'.join(f"{p.get('Player','Unknown')}: {p.get('Appearances','?')} appearances, {p.get('Goals','?')} goals, {p.get('Assists','?')} assists, {p.get('Average rating','?')} average rating" for p in players)
                recommendation+='\nPlayer totals above cover the exported period. Draft stats will use only matched, selected player-match records.'
            extra={}
            if len(preview)>1300:
                extra['file']=discord.File(io.BytesIO((preview+recommendation).encode()),filename='Pep_Result_Preview.txt')
                preview=preview[:1100]+'\n… Full result list attached. Check all entries before confirming.'
            await message.reply('Here are the results I read. Check these before I write your draft (Birmingham score first):\n'+preview+recommendation,**extra,view=RecapConfirmView(self,report['report_id'],request_id),mention_author=False,allowed_mentions=discord.AllowedMentions.none())
        except (ValueError,RuntimeError,TimeoutError,aiohttp.ClientError) as error:
            log.warning('Weekly recap reading failed: %s',type(error).__name__)
            await message.reply((str(error) if isinstance(error,ValueError) else 'I could not read that recap reliably. Please try again. Nothing imported.'),mention_author=False)

    def report_summary(self, report_id):
        report=self.db.report(report_id)
        event=report_event(self.db,report_id)
        cup=event and event['report_type']=='Cup'
        rows=eligible_recap_matches(self.db,report_id)
        selected={m['match_id'] for m in self.db.selected(report_id)}
        title=event['name'] if cup else 'MPL Birmingham City weekly recap'
        lines=['Morning Coach. '+title+'.', 'Send the match recap as Excel (.xlsx), text or a photo, or choose saved matches below. I will prepare a private draft after you confirm your selection.',
               'Period: '+report['week_start'][:10]+' to '+report['week_end'][:10]+' (end exclusive).', '', 'CUP / TOURNAMENT MATCHES' if cup else 'MPL LEAGUE MATCHES']
        lines.extend(('☑' if m['match_id'] in selected else '☐')+f" #{m['match_id']} {match_label(m)}" for m in rows[:4])
        if len(rows)>4:lines.append(f'{len(rows)-4} more available in the selection menus.')
        if not rows:lines.append('No classified matches available.')
        unknown=sum(m['match_type']=='Unknown' for m in self.db.period_matches(report['week_start'],report['week_end']))
        if unknown:lines.append(f'⚠ {unknown} matches still need classification. Use Review Unknown Matches.')
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

        @self.tree.command(name='reportphoto',description='Attach an optional player photo to your weekly draft')
        @app_commands.check(authorized)
        async def reportphoto(interaction,report_id:int,photo:discord.Attachment):
            if interaction.user.id!=self.config.owner_id:
                await interaction.response.send_message('Only Coach can attach a report photo.',ephemeral=True); return
            if photo.size>8*1024*1024:
                await interaction.response.send_message('Photo must be 8 MB or smaller.',ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            try:
                save_photo(self.db,report_id,interaction.user.id,await photo.read())
            except ValueError as error:
                await interaction.followup.send(str(error),ephemeral=True); return
            await interaction.followup.send('Photo saved. Generate the report again to receive it with the private draft.',ephemeral=True)

        @self.tree.command(name='cupreport',description='Select a cup or tournament run for an RT Media article')
        @app_commands.check(authorized)
        async def cupreport(interaction,competition:str='The Minglewood Cup',start_date:str='',end_date:str=''):
            await interaction.response.defer(ephemeral=True)
            try:
                from .scheduler import ET
                from datetime import date
                event=self.db.one("SELECT * FROM competitions WHERE report_type='Cup' AND name=?",(competition,))
                if not event:
                    if not start_date or not end_date:raise ValueError('For a new cup, enter its name, start date and end date (YYYY-MM-DD).')
                    first=date.fromisoformat(start_date);last=date.fromisoformat(end_date)
                    if last<first or not competition.strip() or len(competition)>160:raise ValueError('Use a competition name of 1–160 characters and an ordered date range.')
                    key='cup:'+digest({'name':competition,'start':start_date})[:20]
                    self.db.execute("INSERT OR IGNORE INTO competitions(competition_key,name,report_type,event_start,event_end) VALUES (?,?,'Cup',?,?)",(key,competition,first.isoformat(),last.isoformat()))
                    event=self.db.one('SELECT * FROM competitions WHERE competition_key=?',(key,))
                a=date.fromisoformat(start_date or event['event_start'])
                z=date.fromisoformat(end_date or event['event_end'] or a.isoformat())
                if z<a:raise ValueError('End date must not precede the start.')
                start=datetime.combine(a,datetime.min.time(),ET).astimezone(timezone.utc).isoformat()
                end=datetime.combine(z+timedelta(days=1),datetime.min.time(),ET).astimezone(timezone.utc).isoformat()
                report=self.db.open_report(start,end,self.config.owner_id,event['competition_key'])
                if not report_event(self.db,report['report_id']):configure_report(self.db,report['report_id'],event['competition_key'])
                self.db.set_setting('weekly_dm_awaiting',str(report['report_id']))
                await interaction.followup.send(self.report_summary(report['report_id']),view=ReportView(self,report['report_id']),ephemeral=True)
            except (ValueError,TypeError) as error:await interaction.followup.send(str(error),ephemeral=True)

        @cupreport.autocomplete('competition')
        async def cup_names(interaction,current):
            return [app_commands.Choice(name=e['name'][:100],value=e['name']) for e in self.db.rows("SELECT name FROM competitions WHERE report_type='Cup' ORDER BY event_start DESC") if current.casefold() in e['name'].casefold() and len(e['name'])<=100][:25]

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
