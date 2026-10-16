import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from gaffergpt.schedule_once import make_posts


class CalendarTests(unittest.TestCase):
    def test_calendar_uses_eastern_start_and_links_to_thread(self):
        from gaffergpt.schedule_events import event_spec
        for date, utc_hour in (('2026-10-20', 2), ('2026-11-10', 3)):
            post = next(p for p in make_posts() if p['key'] == date)
            spec = event_spec(post, 123)
            self.assertEqual(spec['kwargs']['start_time'].hour, utc_hour)
            self.assertEqual((spec['kwargs']['end_time'] - spec['kwargs']['start_time']).total_seconds(), 3600)
            self.assertIn('/123', spec['kwargs']['location'])
            self.assertIn('10:30 PM', spec['kwargs']['description'])


class CalendarRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_recovers_event_created_before_receipt(self):
        from gaffergpt.schedule_events import event_spec, publish_events
        from unittest.mock import AsyncMock
        specs = [event_spec(p, 100+i) for i,p in enumerate(make_posts()[:2])]
        events = []
        http = SimpleNamespace(get_scheduled_event=AsyncMock(return_value={"privacy_level": 2}))
        class Guild:
            id = 1524828767426707587
            _state = SimpleNamespace(http=http)
            async def create_scheduled_event(self, **kwargs):
                event = SimpleNamespace(id=1000+len(events), creator_id=42, **{k:v for k,v in kwargs.items() if k != 'reason'})
                events.append(event)
                return event
            async def fetch_scheduled_event(self, event_id):
                return next(e for e in events if e.id == event_id)
        guild = Guild()
        await guild.create_scheduled_event(**specs[0]['kwargs'])
        state = {}
        await publish_events(guild, specs, 42, events.copy(), state, lambda: None)
        self.assertEqual(len(events), 2)
        await publish_events(guild, specs, 42, events.copy(), state, lambda: None)
        self.assertEqual(len(events), 2)
        self.assertEqual(len(state), 2)

    async def test_conflicting_later_event_blocks_all_creation(self):
        from gaffergpt.schedule_events import event_spec, publish_events
        from unittest.mock import AsyncMock
        specs = [event_spec(p, 100+i) for i,p in enumerate(make_posts()[:2])]
        kwargs = specs[1]['kwargs']
        event = SimpleNamespace(id=1, creator_id=999, **{k:v for k,v in kwargs.items() if k != 'reason'})
        guild = SimpleNamespace(id=1524828767426707587, _state=SimpleNamespace(http=SimpleNamespace(get_scheduled_event=AsyncMock(return_value={"privacy_level": 2}))), create_scheduled_event=AsyncMock())
        with self.assertRaises(ValueError):
            await publish_events(guild, specs, 42, [event], {}, lambda: None)
        guild.create_scheduled_event.assert_not_called()

class DiscordEventModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_verification_uses_real_api_privacy_not_broken_library_attribute(self):
        import discord
        from unittest.mock import AsyncMock
        from gaffergpt.schedule_events import event_spec, verify_event
        spec = event_spec(make_posts()[-1], 123)
        fields = spec['kwargs']
        raw = {
            'id': '1000', 'guild_id': '1524828767426707587', 'name': fields['name'],
            'description': fields['description'], 'entity_type': 3, 'entity_id': None,
            'scheduled_start_time': fields['start_time'].isoformat(),
            'scheduled_end_time': fields['end_time'].isoformat(),
            'privacy_level': 2, 'status': 1, 'creator_id': '42',
            'channel_id': None, 'entity_metadata': {'location': fields['location']},
        }
        state = SimpleNamespace(get_user=lambda uid: None,
            http=SimpleNamespace(get_scheduled_event=AsyncMock(return_value=raw)))
        event = discord.ScheduledEvent(state=state, data=raw)
        guild = SimpleNamespace(id=1524828767426707587, _state=state)
        await verify_event(guild, event, spec, 42)
