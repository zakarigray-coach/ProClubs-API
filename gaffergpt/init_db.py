"""Run from the repository root: python -m gaffergpt.init_db."""
import os
from pathlib import Path
from .database import Database


def initialize_database():
    path=os.getenv('GAFFER_DATABASE_PATH',str(Path(__file__).resolve().parents[1]/'gaffergpt.db'))
    Database(path)
    print(f'Database ready: {path}')


if __name__=='__main__':
    initialize_database()
