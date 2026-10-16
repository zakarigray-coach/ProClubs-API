"""One-time, owner-requested removal of the nine MPL schedule forum posts."""
import json
import logging
import os
from pathlib import Path
import discord

log=logging.getLogger('gaffergpt')
GUILD_ID=1524828767426707587
FORUM_ID=1552369533992304660
TARGETS=(
 {'date':'2026-12-03','thread_id':1560498813431578655,'title':'Dec 03 | Birmingham City vs Burnley F.C. | 10 & 10:30 PM ET'},
 {'date':'2026-12-01','thread_id':1560498817449861171,'title':'Dec 01 | Birmingham City vs Brentford FC | 10 & 10:30 PM ET'},
 {'date':'2026-11-24','thread_id':1560498822558515240,'title':'Nov 24 | Birmingham City vs Grimsby Town | 10 & 10:30 PM ET'},
 {'date':'2026-11-12','thread_id':1560498825322307626,'title':'Nov 12 | Birmingham City vs Sunderland AFC | 10 & 10:30 PM ET'},
 {'date':'2026-11-10','thread_id':1560498827624976485,'title':'Nov 10 | Birmingham City vs Middlesbrough | 10 & 10:30 PM ET'},
 {'date':'2026-10-29','thread_id':1560498836609441881,'title':'Oct 29 | Birmingham City vs Everton F.C. | 10 & 10:30 PM ET'},
 {'date':'2026-10-27','thread_id':1560498841776558150,'title':'Oct 27 | Birmingham City vs Man City FC | 10 & 10:30 PM ET'},
 {'date':'2026-10-22','thread_id':1560498844288946299,'title':'Oct 22 | Birmingham City vs Tottenham F.C. | 10 & 10:30 PM ET'},
 {'date':'2026-10-20','thread_id':1560498846453202955,'title':'Oct 20 | Birmingham City vs Man Utd. | 10 & 10:30 PM ET'},
)
ACTION='delete-mpl-season4-2026-v1'

def expected_target(thread_id,title,parent_id,guild_id):
    target=next((x for x in TARGETS if x['thread_id']==thread_id),None)
    return bool(target and target['title']==title and parent_id==FORUM_ID and guild_id==GUILD_ID)

def read_state(path): return json.loads(path.read_text()) if path.exists() else {'deleted':[]}
def write_state(path,state):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(state));temporary.replace(path)

async def run_schedule_delete(bot):
    if os.getenv('PEP_SCHEDULE_DELETE')!=ACTION or getattr(bot,'_mpl_schedule_delete_running',False):return
    bot._mpl_schedule_delete_running=True
    try:
        if bot.config.guild_id!=GUILD_ID:raise ValueError('Wrong server; refusing deletion')
        guild=bot.get_guild(GUILD_ID)
        # Validate all surviving targets before deleting any of them.
        state_path=Path(bot.config.database_path).parent/'mpl-season4-delete.json'
        state=read_state(state_path)
        found=[]
        for item in TARGETS:
            if item['thread_id'] in state['deleted']:continue
            try: thread=await bot.fetch_channel(item['thread_id'])
            except discord.NotFound:raise ValueError(f"Target {item['date']} missing without a deletion receipt")
            if not expected_target(thread.id,thread.name,thread.parent_id,thread.guild.id):
                raise ValueError(f"Target metadata mismatch for {item['date']}")
            message=await thread.fetch_message(thread.id)
            if message.author.id!=bot.user.id or 'BIRMINGHAM CITY — MPL SEASON 4' not in message.content:
                raise ValueError(f"Target author or body mismatch for {item['date']}")
            found.append((item,thread))
        for item,thread in found:
            await thread.delete(reason='Owner requested deletion of the nine MPL schedule posts')
            state['deleted'].append(item['thread_id']);write_state(state_path,state)
            log.info('PEP_SCHEDULE_DELETED date=%s thread=%s',item['date'],item['thread_id'])
        state['complete']=len(state['deleted'])==len(TARGETS)
        write_state(state_path,state)
        log.info('PEP_SCHEDULE_DELETE_COMPLETE count=%s',len(state['deleted']))
    except Exception:log.exception('PEP_SCHEDULE_DELETE_FAILED')
    finally:bot._mpl_schedule_delete_running=False
