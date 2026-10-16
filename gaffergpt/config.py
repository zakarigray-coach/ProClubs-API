import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    token: str
    owner_id: int
    guild_id: int
    management_role_ids: tuple[int,...] = ()
    database_path: str = 'gaffergpt.db'
    rt_media_token: str = ''
    publish_channel_id: int = 0

    @classmethod
    def load(cls):
        token=os.getenv('GAFFER_DISCORD_TOKEN','')
        owner=int(os.getenv('OWNER_DISCORD_USER_ID','0'))
        guild=int(os.getenv('GAFFER_GUILD_ID','0'))
        if not token or not owner or not guild:
            raise ValueError('Set GAFFER_DISCORD_TOKEN, OWNER_DISCORD_USER_ID and GAFFER_GUILD_ID in Railway.')
        return cls(token,owner,guild,
                   tuple(int(x.strip()) for x in os.getenv('GAFFER_MANAGEMENT_ROLE_IDS','').split(',') if x.strip()),
                   os.getenv('GAFFER_DATABASE_PATH',str(Path(__file__).resolve().parents[1]/'gaffergpt.db')),
                   os.getenv('RT_MEDIA_DISCORD_TOKEN',''),int(os.getenv('RT_MEDIA_PUBLISH_CHANNEL_ID','0')))
