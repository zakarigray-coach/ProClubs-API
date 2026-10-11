import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from gaffergpt.database import Database
from gaffergpt.session_reviews import SessionReviews


class Delivery:
    def __init__(self):
        self.messages = {}
        self.sends = 0
        self.fail_after_send = False

    async def find(self, marker, created_at):
        return self.messages.get(marker)

    async def send(self, batch_id, marker):
        self.sends += 1
        self.messages[marker] = 100 + self.sends
        if self.fail_after_send:
            raise RuntimeError('Restart between delivery and database update')
        return self.messages[marker]


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'pep.db'
        self.db = Database(self.path)
        self.now = datetime(2026,10,11,5,tzinfo=timezone.utc)
        self.delivery = Delivery()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, message, minutes_ago=0):
        ids=self.db.ingest(message,2,3,self.now.isoformat(),'Birmingham 2-0 Chelsea',
                           [{'opponent':'Chelsea','birmingham_score':2,'opponent_score':0}])
        if ids:
            self.db.execute('UPDATE matches SET detected_at=? WHERE match_id=?',
                            ((self.now-timedelta(minutes=minutes_ago)).isoformat(),ids[0]))
        return ids

    async def test_waits_then_groups_two_matches_against_same_opponent(self):
        self.add(1,50); self.add(2,20)
        service=SessionReviews(self.db)
        self.assertFalse(await service.tick(self.delivery,self.now))
        self.assertEqual(self.delivery.sends,0)
        self.assertTrue(await service.tick(self.delivery,self.now+timedelta(minutes=40)))
        self.assertEqual(self.delivery.sends,1)
        self.assertEqual(len(service.matches(1)),2)
        self.assertEqual(self.db.official_record()['played'],0)
        self.assertTrue(all(m['match_type']=='Unknown' for m in service.matches(1)))

    async def test_new_recap_extends_wait_and_duplicate_does_not(self):
        self.add(1,70); self.add(2,10)
        self.assertEqual(self.add(2),[])
        self.assertFalse(await SessionReviews(self.db).tick(self.delivery,self.now))
        self.assertTrue(await SessionReviews(self.db).tick(self.delivery,self.now+timedelta(minutes=50)))

    async def test_restart_does_not_send_again_and_next_session_is_separate(self):
        self.add(1,70)
        await SessionReviews(self.db).tick(self.delivery,self.now)
        self.db=Database(self.path)
        self.assertFalse(await SessionReviews(self.db).tick(self.delivery,self.now))
        self.add(2)
        self.assertTrue(await SessionReviews(self.db).tick(self.delivery,self.now,force=True))
        self.assertEqual(self.delivery.sends,2)
        self.assertEqual(len(SessionReviews(self.db).matches(1)),1)
        self.assertEqual(len(SessionReviews(self.db).matches(2)),1)

    async def test_crash_after_send_recovers_marker_without_duplicate(self):
        self.add(1,70)
        self.delivery.fail_after_send=True
        with self.assertRaises(RuntimeError):
            await SessionReviews(self.db).tick(self.delivery,self.now)
        self.db=Database(self.path)
        await SessionReviews(self.db).tick(self.delivery,self.now)
        self.assertEqual(self.delivery.sends,1)
        self.assertEqual(self.db.match(1)['review_message_id'],'101')

    async def test_classified_and_ignored_matches_do_not_trigger_review(self):
        self.add(1);self.add(2)
        self.db.classify(1,'Practice','Unknown',7)
        self.db.classify(2,'Ignored','Unknown',7)
        self.assertFalse(await SessionReviews(self.db).tick(self.delivery,self.now,force=True))

    async def test_force_end_sends_once_without_waiting(self):
        self.add(1)
        service=SessionReviews(self.db)
        self.assertTrue(await service.tick(self.delivery,self.now,force=True))
        self.assertFalse(await service.tick(self.delivery,self.now,force=True))
        self.assertEqual(self.delivery.sends,1)

    async def test_discord_session_controls_support_more_than_twenty_matches(self):
        from types import SimpleNamespace
        from gaffergpt.bot import SessionMatchView, SessionReviewView
        for mid in range(1,27):
            self.add(mid,70)
        service=SessionReviews(self.db)
        batch=service.prepare(self.now)
        bot=SimpleNamespace(db=self.db,session_reviews=service)
        first=SessionMatchView(bot,batch['batch_id'])
        second=SessionMatchView(bot,batch['batch_id'],1)
        self.assertEqual(len(first.children[0].options),20)
        self.assertEqual(len(second.children[0].options),6)
        self.assertTrue(SessionReviewView(bot,batch['batch_id']).is_persistent())
