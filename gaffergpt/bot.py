"""Discord adapter: all football records live in the shared SQLite database."""
import asyncio
import aiohttp
import io
import json
import logging
import math
from .report_verification import ReportHold, digest
from .report_audit import assert_current
import sys
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands
from .config import Config
from .notebook import notebook, daily_backup
from .media_api import start_api
from .analysis import FactualGaffer, tracking_text
from .database import Database, utcnow
from .competitions import report_event, configure_report, set_match_details
from .reporter import Reporter, match_label
from .article_writer import SportsWriter
from .weekly_intake import save_submission, save_photo, content as report_content
from .scheduler import week_window
from .tactical_coach import PracticalCoach
from .coaching_ai import OpenAICoach
from .recap_intake import RecapReader
from .excel_intake import read_excel
from .excel_stats import save_excel_statistics, stats_text, records
from .cup_setup import CupAvailabilityView, run_cup_setup, load as load_cup_setup
from .publisher import PublishError, publish_report

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


def image_mime(data):
    if data[:8]==bytes([0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A]):return 'image/png'
    if data[:3]==bytes([0xFF,0xD8,0xFF]):return 'image/jpeg'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp'
    return None


async def coaching_images(message):
    """Screenshots attached to a coaching DM, passed to the model as supplied evidence."""
    attachments=getattr(message,'attachments',[])
    if len(attachments)>4:
        raise ValueError('Send up to four screenshots at a time.')
    images=[]
    for attachment in attachments:
        if attachment.size>8*1024*1024:
            raise ValueError('Each screenshot must be 8 MB or smaller.')
        data=await attachment.read()
        mime=image_mime(data)
        if not mime:
            raise ValueError('I can read PNG, JPEG or WebP screenshots. Video clips are not supported yet; send a screenshot instead.')
        images.append((data,mime))
    return images


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
        async def publish(interaction):
            if interaction.user.id!=bot.config.owner_id:
                await interaction.response.send_message('Only Coach can publish.',ephemeral=True); return
            await interaction.response.defer(ephemeral=True)
            try:
                ids,fresh=await publish_report(bot.db,report_id,bot.config.rt_media_token,bot.config.publish_channel_id)
            except (PublishError,ReportHold,ValueError) as error:
                await interaction.followup.send(str(error),ephemeral=True); return
            except (aiohttp.ClientError,asyncio.TimeoutError):
                await interaction.followup.send('Discord could not be reached. Tap Publish again; anything already posted will not be repeated.',ephemeral=True); return
            link=f'https://discord.com/channels/{bot.config.guild_id}/{bot.config.publish_channel_id}/{ids[0]}'
            await interaction.followup.send(('Published by RT Football Media: ' if fresh else 'Already published, nothing was posted again: ')+link,ephemeral=True)
        self.add_item(Action('Approve Draft (save only)',f'gaffer:approve:{report_id}',approve,discord.ButtonStyle.success))
        self.add_item(Action('Publish to MPL Announcements',f'rt:publish:{report_id}',publish,discord.ButtonStyle.danger))
        self.add_item(Action('Change Selection',f'gaffer:change:{report_id}',change))


class GafferBot(discord.Client):
    def __init__(self, config):
        intents=discord.Intents.default(); intents.message_content=True
        super().__init__(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        self.config=config; self.db=Database(config.database_path)
        self.cup_availability_lock=asyncio.Lock()
        self.coach=OpenAICoach.from_environment()
        self.coaching_lock=asyncio.Lock()
        self.recap_reader=RecapReader(self.coach) if self.coach else None
        self.reporter=Reporter(self.db,writer=SportsWriter(self.coach.key) if self.coach else None)
        self.tree=app_commands.CommandTree(self)
        self.worker=None
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

    async def work(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                try:
                    await asyncio.to_thread(daily_backup,self.db)
                except Exception as error:
                    log.error('Daily backup failed: %s',type(error).__name__)
            except Exception as error:
                log.error('Background check failed: %s',type(error).__name__)
            await asyncio.sleep(3600)

    async def on_error(self, event_method, *args, **kwargs):
        error=sys.exc_info()[1]
        log.error('Discord event %s failed: %s',event_method,type(error).__name__)

    async def on_ready(self):
        log.info('Pep connected; guild=%s',self.config.guild_id)
        await run_cup_setup(self)

    async def close(self):
        if self.worker:
            self.worker.cancel()
        if self.media_runner:
            await self.media_runner.cleanup()
        await super().close()

    def saved_formation(self):
        tactic=self.db.one('SELECT * FROM squad_tactics ORDER BY rowid DESC LIMIT 1')
        if not tactic:
            return ''
        notes=f"; {tactic['custom_instructions']}" if tactic['custom_instructions'] else ''
        return f"{tactic['formation']} ({tactic['tactic_name']}; build-up {tactic['build_up_style']}; depth {tactic['defensive_depth']}{notes})"

    async def coaching_advice(self, user_id, request_id, analysis, formation='', images=()):
        analysis=analysis.strip() or ('Analyse the attached screenshot.' if images else '')
        if not analysis or len(analysis)>12000:
            raise ValueError('Send your question or analysis as text, up to 12,000 characters.')
        formation=formation or self.saved_formation()
        async with self.coaching_lock:
            saved=self.db.one('SELECT advice FROM coaching_notes WHERE request_id=?',(str(request_id),))
            if saved:
                return saved['advice']
            provider='practical-library'
            if self.coach:
                try:
                    advice=await self.coach.advise(analysis,formation,images)
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
            # A plain question is a coaching request even while a recap is open.
            question=message.content.strip().endswith('?') and not getattr(message,'attachments',[])
            if report and report['status'] not in ('approved','skipped') and not question and not message.content.lower().startswith(('tactics:', 'coaching:')):
                await self.read_weekly_dm(message,report)
                return
            try:
                images=await coaching_images(message)
                async with message.channel.typing():
                    advice=await self.coaching_advice(message.author.id,message.id,message.content,images=images)
            except ValueError as error:
                await message.reply(str(error),mention_author=False)
                return
            kwargs={'embed':self.coaching_embed(advice),'mention_author':False}
            if len(advice)>3900:
                kwargs['file']=discord.File(io.BytesIO(advice.encode()),filename='pep-tactical-advice.txt')
            await message.reply(**kwargs)

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

        @self.tree.command(name='tacticaladvice',description='Ask Pep a tactical question or paste your match analysis')
        @app_commands.check(authorized)
        @app_commands.describe(analysis='Your question, observations or pasted analysis',formation='Optional: tonight’s formation if different from the saved one')
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
            await interaction.response.send_message(f'Pep is online. AI runs only when you ask. {unknown} saved matches are still unclassified.',ephemeral=True)

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
