import unittest
from gaffergpt.schedule_delete import TARGETS, FORUM_ID, GUILD_ID, expected_target

class ScheduleDeletionScopeTests(unittest.TestCase):
 def test_manifest_is_exactly_nine_known_schedule_posts(self):
  self.assertEqual(len(TARGETS),9)
  self.assertEqual(len({x['thread_id'] for x in TARGETS}),9)
  self.assertEqual({x['date'] for x in TARGETS},{'2026-12-03','2026-12-01','2026-11-24','2026-11-12','2026-11-10','2026-10-29','2026-10-27','2026-10-22','2026-10-20'})
  self.assertTrue(all(expected_target(x['thread_id'],x['title'],FORUM_ID,GUILD_ID) for x in TARGETS))
 def test_refuses_other_forums_servers_ids_and_titles(self):
  target=TARGETS[0]
  self.assertFalse(expected_target(target['thread_id'],target['title'],FORUM_ID+1,GUILD_ID))
  self.assertFalse(expected_target(target['thread_id'],target['title'],FORUM_ID,GUILD_ID+1))
  self.assertFalse(expected_target(target['thread_id']+1,target['title'],FORUM_ID,GUILD_ID))
  self.assertFalse(expected_target(target['thread_id'],'other post',FORUM_ID,GUILD_ID))
