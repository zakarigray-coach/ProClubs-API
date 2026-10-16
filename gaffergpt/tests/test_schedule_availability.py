import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from gaffergpt.schedule_availability import AvailabilityStore, render, ScheduleAvailabilityView, PLAYER_ROLE_ID
from gaffergpt.schedule_once import make_posts, GUILD_ID

class AvailabilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'availability.json';self.store=AvailabilityStore(self.path)
  self.post=make_posts()[-1];self.now=datetime(2026,10,16,tzinfo=timezone.utc)
 def vote(self,uid,status,**kw):
  return self.store.vote(self.post['key'],uid,f'Player {uid}',kw.get('roles',[PLAYER_ROLE_ID]),status,kw.get('guild',GUILD_ID),kw.get('thread',10),10,now=kw.get('now',self.now))
 def test_changed_response_replaces_and_survives_restart(self):
  self.vote(1,'yes');self.vote(2,'yes');self.vote(1,'no')
  store=AvailabilityStore(self.path)
  body=render(self.post,store.responses(self.post['key']))
  self.assertIn('Available: 1',body);self.assertIn('Unavailable: 1',body)
  self.assertEqual(len(store.responses(self.post['key'])['1']),2)
 def test_nights_are_independent(self):
  self.vote(1,'yes')
  self.assertEqual(self.store.responses('2026-10-22'),{})
 def test_unauthorized_wrong_channel_and_kickoff_are_rejected(self):
  for kw in [dict(roles=[]),dict(guild=1),dict(thread=11),dict(now=datetime(2026,10,21,2,tzinfo=timezone.utc))]:
   with self.subTest(kw=kw),self.assertRaises(ValueError):self.vote(1,'yes',**kw)
  self.assertEqual(self.store.responses(self.post['key']),{})
 def test_november_cutoff_uses_corrected_eastern_time(self):
  self.store.vote('2026-11-10',1,'P',[PLAYER_ROLE_ID],'yes',GUILD_ID,10,10,now=datetime(2026,11,11,2,30,tzinfo=timezone.utc))
  with self.assertRaises(ValueError):self.store.vote('2026-11-10',1,'P',[PLAYER_ROLE_ID],'yes',GUILD_ID,10,10,now=datetime(2026,11,11,3,tzinfo=timezone.utc))

class ViewTests(unittest.IsolatedAsyncioTestCase):
 async def test_buttons_are_persistent(self):
  import asyncio
  with tempfile.TemporaryDirectory() as tmp:
   view=ScheduleAvailabilityView(AvailabilityStore(Path(tmp)/'votes.json'),make_posts()[-1],10,asyncio.Lock())
   self.assertTrue(view.is_persistent())
   self.assertEqual([b.label for b in view.children],['10:00 • Available','10:00 • Maybe','10:00 • Unavailable','10:30 • Available','10:30 • Maybe','10:30 • Unavailable'])
