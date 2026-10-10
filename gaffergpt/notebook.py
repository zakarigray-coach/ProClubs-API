"""Portable notebook exports and SQLite snapshots, using the central database."""
import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


TABLES={'Matches':'matches','Club_Stats':'match_statistics','Players':'players',
        'Player_Links':'player_links','Tactics':'squad_tactics','Reports':'weekly_reports',
        'Selected_Matches':'report_matches','Schedule_History':'weekly_jobs'}


def notebook(db):
    buffer=io.BytesIO()
    with db.connect() as conn,zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        conn.execute('BEGIN')  # One consistent view across every file.
        for title,table in TABLES.items():
            query=f'SELECT * FROM {table}'
            if title=='Club_Stats':
                query+=" WHERE subject_type='team'"
            cursor=conn.execute(query); headers=[d[0] for d in cursor.description]
            output=io.StringIO(); writer=csv.writer(output);writer.writerow(headers)
            for row in cursor:
                cells=[]
                for value in row:
                    value='' if value is None else value
                    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
                        value="'"+value  # Prevent spreadsheet formulas from untrusted recap text.
                    cells.append(value)
                writer.writerow(cells)
            archive.writestr(f'Peps_Notebook_{title}.csv',output.getvalue().encode('utf-8-sig'))
        archive.writestr('READ_ME.txt','Pep’s Notebook is a download snapshot, not a live Google Sheet. Import CSV files into Sheets or Excel. Matches keep separate IDs. Only counts_official=1 belongs in the official record. Selected_Matches joins reports to selected match IDs. Club_Stats contains team metrics only. Empty cells mean missing information. Files may contain private club data; share intentionally. Discord IDs should be imported as text to preserve their exact digits.')
    if len(buffer.getvalue())>7_500_000:
        raise ValueError('Notebook exceeds the Discord download limit. Ask for a reporting-period export.')
    return buffer.getvalue()


def daily_backup(db, now=None, refresh=False):
    now=now or datetime.now(timezone.utc)
    folder=Path(db.path).parent/'backups';folder.mkdir(exist_ok=True)
    target=folder/f'pep-{now.date().isoformat()}.sqlite3'
    if refresh or not target.exists():
        temporary=target.with_suffix('.tmp')
        with db.connect() as source,sqlite3.connect(temporary) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('Backup integrity check failed.')
        temporary.replace(target)
    for old in sorted(folder.glob('pep-*.sqlite3'))[:-7]:
        old.unlink()
    return target
