import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gaffergpt.schedule_once import make_posts, ACTION, GUILD_ID
from gaffergpt.schedule_availability import AvailabilityStore, ScheduleAvailabilityView, PLAYER_ROLE_ID, render


class CorrectedScheduleTests(unittest.TestCase):
    def test_every_night_is_home_then_away(self):
        posts = make_posts()
        self.assertEqual(len(posts), 9)
        for post in posts:
            self.assertIn('10:00 PM ET — HOME', post['content'])
            self.assertIn('10:30 PM ET — AWAY', post['content'])
        self.assertEqual(ACTION, 'mpl-season4-2026-v2')


class FixtureAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'votes.json'
        self.store = AvailabilityStore(self.path)
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)

    def vote(self, fixture, status, **kwargs):
        return self.store.vote('2026-10-20', 1, 'Player', [PLAYER_ROLE_ID], status,
                               GUILD_ID, 10, 10, fixture=fixture, now=kwargs.get('now', self.now))

    def test_fixture_choices_are_independent_and_survive_restart(self):
        self.vote(1, 'yes')
        self.vote(2, 'no')
        self.vote(1, 'maybe')
        votes = AvailabilityStore(self.path).responses('2026-10-20')
        self.assertEqual(votes['1']['1']['status'], 'maybe')
        self.assertEqual(votes['2']['1']['status'], 'no')
        self.assertEqual(self.store.responses('2026-10-22'), {})
        body = render(make_posts()[-1], votes)
        self.assertIn('Maybe: 1', body)
        self.assertIn('Unavailable: 1', body)

    def test_each_fixture_closes_at_its_own_kickoff(self):
        at_1015 = datetime(2026, 10, 21, 2, 15, tzinfo=timezone.utc)
        with self.assertRaises(ValueError): self.vote(1, 'yes', now=at_1015)
        self.vote(2, 'yes', now=at_1015)
        with self.assertRaises(ValueError):
            self.vote(2, 'yes', now=datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc))

    def test_november_cutoff_preserves_ten_pm_after_dst(self):
        self.store.vote('2026-11-10', 1, 'Player', [PLAYER_ROLE_ID], 'yes', GUILD_ID, 10, 10,
                        fixture=1, now=datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            self.store.vote('2026-11-10', 1, 'Player', [PLAYER_ROLE_ID], 'yes', GUILD_ID, 10, 10,
                            fixture=1, now=datetime(2026, 11, 11, 3, tzinfo=timezone.utc))


class FixtureButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_six_persistent_buttons_identify_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            view = ScheduleAvailabilityView(AvailabilityStore(Path(tmp) / 'v.json'),
                                            make_posts()[-1], 10, asyncio.Lock())
            self.assertTrue(view.is_persistent())
            self.assertEqual(len(view.children), 6)
            self.assertEqual(len({b.custom_id for b in view.children}), 6)
            self.assertEqual([b.row for b in view.children], [0, 0, 0, 1, 1, 1])

    async def test_button_callbacks_save_the_selected_fixture_and_refresh_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AvailabilityStore(Path(tmp) / 'v.json')
            view = ScheduleAvailabilityView(store, make_posts()[-1], 10, asyncio.Lock())
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=123, display_name='Keeper', roles=[SimpleNamespace(id=PLAYER_ROLE_ID)]),
                guild_id=GUILD_ID, channel_id=10,
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
                message=SimpleNamespace(id=10, edit=AsyncMock()),
            )
            # Press first-match Available, then second-match Maybe.
            await view.children[0].callback(interaction)
            await view.children[4].callback(interaction)
            votes = store.responses('2026-10-20')
            self.assertEqual(votes['1']['123']['status'], 'yes')
            self.assertEqual(votes['2']['123']['status'], 'maybe')
            content = interaction.message.edit.call_args.kwargs['content']
            self.assertIn('Available: 1 — Keeper', content)
            self.assertIn('Maybe: 1 — Keeper', content)

    async def test_nonplayer_button_press_does_not_store_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AvailabilityStore(Path(tmp) / 'v.json')
            view = ScheduleAvailabilityView(store, make_posts()[-1], 10, asyncio.Lock())
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=123, display_name='Visitor', roles=[]),
                guild_id=GUILD_ID, channel_id=10,
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
                message=SimpleNamespace(id=10, edit=AsyncMock()),
            )
            await view.children[0].callback(interaction)
            self.assertEqual(store.responses('2026-10-20'), {})
            interaction.message.edit.assert_not_called()
