import unittest
from gaffergpt.schedule_once import make_posts

class ScheduleTests(unittest.TestCase):
 def test_dates_reverse_and_both_legs_preserved(self):
  posts=make_posts()
  self.assertEqual(len(posts),9)
  self.assertIn('Dec 03',posts[0]['title'])
  self.assertIn('Oct 20',posts[-1]['title'])
  self.assertIn('Birmingham City vs Man Utd.',posts[-1]['content'])
  self.assertIn('Man Utd. vs Birmingham City',posts[-1]['content'])
  self.assertIn('10:00 PM ET',posts[-1]['content'])
  self.assertIn('10:00 PM ET',posts[0]['content'])
  self.assertEqual(len({p['key'] for p in posts}),9)

from types import SimpleNamespace
from gaffergpt.schedule_once import publish_posts

class FakeThread:
 def __init__(self,i,p,author=42):
  self.id=i;self.name=p['title'];self.message=SimpleNamespace(content=p['content'],author=SimpleNamespace(id=author))
 async def fetch_message(self,i): return self.message

class FakeForum:
 def __init__(self): self.created=[];self.available_tags=[]
 async def create_thread(self,**kwargs):
  t=FakeThread(100+len(self.created),dict(title=kwargs['name'],content=kwargs['content']))
  self.created.append(t)
  return SimpleNamespace(thread=t)

class PostingTests(unittest.IsolatedAsyncioTestCase):
 async def test_restart_recovers_send_before_receipt_without_duplicate(self):
  p=make_posts()[:2];forum=FakeForum();existing=[FakeThread(90,p[0])];receipts={}
  await publish_posts(forum,p,42,existing,receipts.__setitem__)
  self.assertEqual(len(forum.created),1)
  self.assertEqual(receipts[p[0]['key']],90)
  await publish_posts(forum,p,42,existing,receipts.__setitem__)
  self.assertEqual(len(forum.created),1)
 async def test_conflicting_post_is_not_overwritten(self):
  p=make_posts()[:1];forum=FakeForum()
  with self.assertRaises(ValueError):
   await publish_posts(forum,p,42,[FakeThread(90,p[0],author=43)],lambda *x:None)
  self.assertEqual(forum.created,[])
