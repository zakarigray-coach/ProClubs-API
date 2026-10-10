import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    token: str
    owner_id: int
    guild_id: int
    recap_channel_id: int = 0
    source_bot_id: int = 0
    management_role_ids: tuple[int,...] = ()
    database_path: str = 'gaffergpt.db'
    schedule_enabled: bool = False

    @classmethod
    def load(cls):
        token=os.getenv('GAFFER_DISCORD_TOKEN','')
        owner=int(os.getenv('OWNER_DISCORD_USER_ID','0'))
        guild=int(os.getenv('GAFFER_GUILD_ID','0'))
        if not token or not owner or not guild:
            raise ValueError('Set GAFFER_DISCORD_TOKEN, OWNER_DISCORD_USER_ID and GAFFER_GUILD_ID in Railway.')
        return cls(token,owner,guild,int(os.getenv('OURPROCLUBS_CHANNEL_ID','0')),
                   int(os.getenv('OURPROCLUBS_BOT_ID','0')),
                   tuple(int(x.strip()) for x in os.getenv('GAFFER_MANAGEMENT_ROLE_IDS','').split(',') if x.strip()),
                   os.getenv('GAFFER_DATABASE_PATH',str(Path(__file__).resolve().parents[1]/'gaffergpt.db')),
                   os.getenv('PEP_FRIDAY_RECAP',os.getenv('GAFFER_FRIDAY_ENABLED','false')).lower()=='true')
