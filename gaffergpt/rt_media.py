"""RT Football Media's own Discord identity.

Pep hands over an approved week; this client delivers the draft to Coach, takes
his approval and publishes. It shares Pep's database and makes no football decisions.
"""
import logging
import discord
from .bot import DraftView, GafferBot

log=logging.getLogger('rt_media')


class RTMediaBot(discord.Client):
    # The newsroom reuses the same permission check, summary text and photo handling as Pep.
    manager=GafferBot.manager
    report_summary=GafferBot.report_summary
    attach_weekly_photo=GafferBot.attach_weekly_photo

    def __init__(self, pep):
        intents=discord.Intents.none(); intents.guilds=True; intents.dm_messages=True
        super().__init__(intents=intents,allowed_mentions=discord.AllowedMentions.none())
        self.db=pep.db; self.config=pep.config; self.reporter=pep.reporter

    def media_desk(self):
        return self

    async def setup_hook(self):
        for report in self.db.rows("SELECT report_id FROM weekly_reports WHERE status!='skipped'"):
            self.add_view(DraftView(self,report['report_id']))

    async def on_ready(self):
        log.info('RT Football Media connected as %s',self.user)

    async def on_message(self, message):
        # Only Coach's photo for an open draft is handled here; everything else belongs to Pep.
        if message.author.bot or message.guild is not None or message.author.id!=self.config.owner_id:
            return
        report=self.db.setting('weekly_photo_awaiting','')
        if not report.isdigit():
            return
        if message.content.strip().lower()=='cancel photo':
            self.db.set_setting('weekly_photo_awaiting','')
            await message.reply('Photo attachment cancelled.',mention_author=False); return
        if message.attachments:
            await self.attach_weekly_photo(message,int(report))
