import unittest
from types import SimpleNamespace
from datetime import datetime,timezone
import discord
from gaffergpt.recap_check import inspect_league_stats,readable_message


class RecapCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_inspection_is_bounded_and_only_reads_requested_channels(self):
        calls=[]
        embed=discord.Embed(title='MPL Birmingham · W 2–0 vs Gougherton FC')
        embed.add_field(name='Team stats',value='Us Them\nShots 12 3\nPass % 79% 67%')
        message=SimpleNamespace(id=123,content='',embeds=[embed],attachments=[],
            created_at=datetime.now(timezone.utc),author=SimpleNamespace(bot=True,id=99,name='Pro Clubs Tracker'))
        async def history(**kwargs):
            calls.append(kwargs)
            yield message
        channel=SimpleNamespace(id=20,name='⚽league-game-stats',history=history)
        async def forbidden_history(**kwargs):
            self.fail('Unrelated channel must never be read')
            yield message
        other=SimpleNamespace(id=21,name='management',history=forbidden_history)
        class Guild:
            async def fetch_channels(self): return [channel,other]
        bot=SimpleNamespace(config=SimpleNamespace(guild_id=30),get_guild=lambda guild_id:Guild())
        result=await inspect_league_stats(bot)
        self.assertEqual(calls,[{'limit':30}])
        self.assertEqual(result['channels'],[{'id':'20','name':'⚽league-game-stats'}])
        self.assertEqual(result['recaps'][0]['message_id'],'123')
        self.assertIn('Shots 12 3',result['recaps'][0]['text'])

    def test_repeated_embed_body_is_not_imported_twice(self):
        content='MPL Birmingham 2-1 Chelsea'
        message=SimpleNamespace(content=content,embeds=[discord.Embed(description=content)])
        self.assertEqual(readable_message(message),content)
