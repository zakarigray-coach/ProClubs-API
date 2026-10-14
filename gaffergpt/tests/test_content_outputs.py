import unittest
from gaffergpt.tests import test_mvp_recap as fixtures

class OutputTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.MVPTests.asyncSetUp
    asyncTearDown=fixtures.MVPTests.asyncTearDown
    league=fixtures.MVPTests.league
class PureOutputTests(unittest.TestCase):
    def test_dynamic_stats_only_use_complete_verified_facts(self):
        from gaffergpt.recap_output import select_player_stats
        facts={str(i):dict(kind='player',subject='Max',metric=m,value=v,classification='Official',fixture_id=None) for i,(m,v) in enumerate([('saves',12),('clean_sheets',2),('average_rating',8.4),('goals',0),('assists',0)])}
        stats=select_player_stats({'facts':facts},'Max','Official')
        self.assertEqual([s['metric'] for s in stats],['saves','clean_sheets','average_rating'])
        self.assertTrue(all(s['fact_id'] in facts for s in stats))
        self.assertEqual(select_player_stats({'facts':facts},'Missing','Official'),[])
        self.assertEqual(select_player_stats({'facts':facts},'Max','Cup'),[])
    def test_scorer_can_have_defensive_statistics(self):
        from gaffergpt.recap_output import select_player_stats
        facts={str(i):dict(kind='player',subject='Coach',metric=m,value=v,classification='Official',fixture_id=None) for i,(m,v) in enumerate([('goals',1),('tackles_won',12),('interceptions',8),('appearances',4)])}
        stats=select_player_stats({'facts':facts},'Coach','Official')
        self.assertEqual([s['metric'] for s in stats],['goals','tackles_won','interceptions'])

    def test_discord_chunks_preserve_paragraphs_and_reject_oversized_one(self):
        from gaffergpt.recap_output import discord_chunks
        text='a'*1100+'\n\n'+'b'*1100
        self.assertEqual(discord_chunks(text),['a'*1100,'b'*1100])
        with self.assertRaises(ValueError):discord_chunks('a'*2001)
        with self.assertRaises(ValueError):discord_chunks('⚽'+'😀'*1000)

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_article_sent_as_readable_messages_without_mentions(self):
        from unittest.mock import AsyncMock
        from gaffergpt.bot import send_article_text
        from types import SimpleNamespace
        target=SimpleNamespace(send=AsyncMock())
        article='First paragraph.\n\n'+'Second paragraph. '*110
        await send_article_text(target,article)
        messages=target.send.call_args_list
        self.assertEqual('\n\n'.join(c.args[0] for c in messages),article.strip())
        self.assertTrue(all(not c.kwargs['allowed_mentions'].everyone for c in messages))

class FixedCoverTests(unittest.TestCase):
    def test_passing_and_defensive_stats_fit_fixed_strip(self):
        from gaffergpt.article_layout import weekly_cover
        from gaffergpt.recap_output import select_player_stats
        summary=dict(wins=1,draws=1,losses=0,goals_for=5,goals_against=3)
        for metrics in [dict(tackles_won=28,interceptions=14,pass_accuracy=88.7),dict(pass_accuracy=91.2,passes_completed=234,average_rating=8.43)]:
            facts={str(i):dict(kind='player',subject='Max',metric=m,value=v,classification='Cup',fixture_id=None) for i,(m,v) in enumerate(metrics.items())}
            payload={'report_label':'CUP EDITION','supporting_headline':'5 scored, 3 conceded across 2 matches.','player_of_the_week':{'award_label':'Player of the Tournament','statistics':select_player_stats({'facts':facts},'Max','Cup')}}
            data=weekly_cover('Blues Under The Cup Spotlight','October 12–October 18, 2026',summary,'Max',payload=payload)
            self.assertTrue(data.startswith(b'\x89PNG'))
