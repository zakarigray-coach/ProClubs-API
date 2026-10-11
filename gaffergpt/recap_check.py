"""Bounded, read-only recap inspection using Pep's own Discord connection."""
import re


def readable_message(message):
    blocks=[]
    def add(value):
        if value and value.strip() and value.strip() not in blocks:
            blocks.append(value.strip())
    add(message.content)
    for embed in getattr(message,'embeds',[]):
        add(embed.title); add(embed.description)
        for field in embed.fields:
            separator='\n' if field.name.strip().upper() in ('PLAYER STATS','TEAM STATS','FINAL SCORE') else ': '
            add(f'{field.name}{separator}{field.value}')
    return '\n'.join(blocks)


async def inspect_league_stats(bot):
    # Only the requested server/channel names; never broad server message scans.
    guild=bot.get_guild(bot.config.guild_id)
    if guild is None:
        raise ValueError('Configured server is unavailable.')
    channels=await guild.fetch_channels()
    matches=[c for c in channels if re.sub(r'[^a-z0-9]','',c.name.casefold()) in ('leaguestats','leaguegamestats')]
    result={'channels':[],'recaps':[]}
    for channel in matches:
        result['channels'].append({'id':str(channel.id),'name':channel.name})
        found=0
        async for message in channel.history(limit=30):
            text=readable_message(message)
            if not message.author.bot or not re.search(r'mpl\s+birmingham|birmingham\s+city',text,re.I):
                continue
            result['recaps'].append({'channel_id':str(channel.id),'channel_name':channel.name,
                'message_id':str(message.id),'author_id':str(message.author.id),
                'author_name':message.author.name,'created_at':message.created_at.isoformat(),
                'text':text[:18000],'truncated':len(text)>18000,
                'embed_count':len(getattr(message,'embeds',[])),
                'attachment_count':len(getattr(message,'attachments',[]))})
            found+=1
            if found==3:
                break
    return result
