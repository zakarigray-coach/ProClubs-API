import asyncio,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from gaffergpt.database import Database
from gaffergpt.cup_setup import CUP_ID,KEY,TITLE
from gaffergpt import cup_setup

class GameplanTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.db=Database(Path(self.temp.name)/'test.db');self.messages=[];self.fail_at=None
  self.channel=NS(id=1559595763015876752,guild=NS(id=1524828767426707587),name=TITLE,archived=False,send=self.send,history=self.history,fetch_message=self.fetch_message)
  self.bot=NS(db=self.db,user=NS(id=1),fetch_channel=self.fetch_channel,cup_availability_lock=asyncio.Lock())
  self.db.set_setting(KEY,json.dumps({'guild_id':self.channel.guild.id,'forum_post_id':self.channel.id,'player_role_id':1549476136893812866,'status':'complete'}))
 async def fetch_channel(self,_):return self.channel
 async def fetch_message(self,i):return next(m for m in self.messages if m.id==i)
 async def history(self,**kwargs):
  for m in reversed(self.messages):yield m
 async def send(self,content,allowed_mentions):
  if self.fail_at==len(self.messages):raise RuntimeError('send failed')
  m=NS(id=100+len(self.messages),author=self.bot.user,content=content,allowed_mentions=allowed_mentions);self.messages.append(m);return m
 async def run_action(self):
  with patch.dict('os.environ',{'PEP_CUP_GAMEPLAN_REQUEST':CUP_ID}):await cup_setup.run_cup_gameplan(self.bot)
 async def test_posts_one_message_and_restart_does_not_duplicate(self):
  self.assertTrue(hasattr(cup_setup,'run_cup_gameplan'),'one-time gameplan action is missing')
  await self.run_action();await self.run_action()
  self.assertEqual(len(self.messages),1)
  self.assertIn('ThorfinnKenobi',self.messages[0].content);self.assertIn('midfield',self.messages[0].content)
  self.assertIn('Make the keeper change position before we shoot',self.messages[0].content)
  self.assertIn('4-2-3-1',self.messages[0].content)
  self.assertIn('<@&1549476136893812866>',self.messages[0].content)
  self.assertEqual([r.id for r in self.messages[0].allowed_mentions.roles],[1549476136893812866])
  self.assertTrue(all(len(m.content)<=2000 for m in self.messages))
 async def test_retry_after_send_failure(self):
  self.assertTrue(hasattr(cup_setup,'run_cup_gameplan'),'one-time gameplan action is missing')
  self.fail_at=0;await self.run_action();self.assertEqual(len(self.messages),0)
  self.fail_at=None;await self.run_action();self.assertEqual(len(self.messages),1)
 async def test_wrong_thread_sends_nothing(self):
  self.assertTrue(hasattr(cup_setup,'run_cup_gameplan'),'one-time gameplan action is missing')
  self.channel.id=999;await self.run_action();self.assertEqual(self.messages,[])
