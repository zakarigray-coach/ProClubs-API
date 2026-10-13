import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from gaffergpt.database import Database
from gaffergpt.cup_setup import setup_cup, save_availability, CUP_ID, body

class CupSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Database(Path(self.temp.name)/'cup.db')
        self.poster=Path(self.temp.name)/'poster.jpg';self.poster.write_bytes(b'poster')
        self.now=datetime(2026,10,13,16,tzinfo=timezone.utc)
        self.posts=[];self.events=[];self.sent=[]
        self.message=NS(id=101,edit=self.edit)
        self.thread=NS(id=100,name='unused',owner_id=1,archived=False,fetch_message=self.fetch_message,send=self.send,history=self.history)
        self.forum=NS(id=10,name='📅・mpl-match-center',threads=[],available_tags=[],create_thread=self.create_thread,
          permissions_for=lambda _:NS(view_channel=True,send_messages=True,send_messages_in_threads=True,read_message_history=True,attach_files=True,mention_everyone=True),archived_threads=self.archived)
        self.live=NS(id=20,name='📺・live-games')
        self.role=NS(id=30,name='Birmingham City players',mentionable=False)
        self.guild=NS(id=99,channels=[self.forum,self.live],roles=[self.role],me=NS(id=1,guild_permissions=NS(create_events=True)),
          fetch_channels=self.fetch_channels,fetch_roles=self.fetch_roles,fetch_scheduled_events=self.fetch_events,create_scheduled_event=self.create_event,fetch_channel=self.fetch_channel)
    async def edit(self,**kwargs):self.message.content=kwargs['content'];self.message.view=kwargs['view'];return self.message
    async def fetch_message(self,_):return self.message
    async def send(self,**kwargs):self.sent.append(kwargs);return NS(id=102)
    async def history(self,**kwargs):
        if False:yield None
    async def archived(self,**kwargs):
        if False:yield None
    async def fetch_channels(self):return self.guild.channels
    async def fetch_roles(self):return self.guild.roles
    async def fetch_events(self):return self.events
    async def fetch_channel(self,_):return self.thread
    async def create_thread(self,**kwargs):
        self.thread.name=kwargs['name'];self.posts.append(kwargs);self.forum.threads.append(self.thread)
        return NS(thread=self.thread,message=self.message)
    async def create_event(self,**kwargs):
        event=NS(id=200,name=kwargs['name'],start_time=kwargs['start_time']);self.events.append(event);self.event_data=kwargs;return event
    async def setup(self):return await setup_cup(self.guild,self.db,now=self.now,poster_path=self.poster)
    async def test_post_event_ping_and_restart(self):
        record=await self.setup()
        self.assertEqual(record['status'],'complete');self.assertEqual(len(self.posts),1)
        self.assertIn('8:00 PM ET',self.message.content);self.assertIn('8:30 PM ET',self.message.content)
        self.assertIn('10:00 PM ET',self.message.content);self.assertIn('Single elimination',self.message.content)
        self.assertIn('<#20>',self.message.content);self.assertNotIn('https://discord.com/',self.message.content)
        self.assertEqual([b.label for b in self.message.view.children],['YES — Available','NO — Unavailable'])
        self.assertEqual(self.event_data['start_time'].isoformat(),'2026-10-14T02:00:00+00:00')
        self.assertEqual([r.id for r in self.sent[0]['allowed_mentions'].roles],[30])
        self.db=Database(Path(self.temp.name)/'cup.db');await self.setup()
        self.assertEqual(len(self.posts),1);self.assertEqual(len(self.events),1);self.assertEqual(len(self.sent),1)
    async def test_failure_resumes_without_duplicate_post(self):
        original=self.guild.create_scheduled_event
        async def failed(**kwargs):raise RuntimeError('event unavailable')
        self.guild.create_scheduled_event=failed
        with self.assertRaisesRegex(RuntimeError,'event unavailable'):await self.setup()
        self.guild.create_scheduled_event=original;await self.setup();self.assertEqual(len(self.posts),1)
    async def test_votes_replace_and_concurrent_players_survive(self):
        await self.setup()
        for uid,status in [(42,'yes'),(42,'no'),(43,'yes')]:
            result=save_availability(self.db,uid,str(uid),[30],status,99,100,now=self.now)
        self.assertEqual(result['availability']['42']['status'],'no')
        self.assertEqual(len(result['availability']),2)
        self.assertIn('YES: 1',body(result));self.assertIn('NO: 1',body(result))
        with self.assertRaisesRegex(ValueError,'Only Birmingham City players'):
            save_availability(self.db,44,'outsider',[], 'yes',99,100,now=self.now)
    async def test_ambiguous_channel_fails_before_posting(self):
        self.guild.channels.append(NS(id=21,name='live-games'))
        with self.assertRaisesRegex(ValueError,'Live Games'):await self.setup()
        self.assertEqual(self.posts,[])
