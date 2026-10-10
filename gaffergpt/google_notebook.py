"""One-way Google Sheets mirror; SQLite remains the source of truth."""
import asyncio
import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from .notebook import TABLES

log = logging.getLogger('gaffergpt')


class SyncRejected(RuntimeError):
    """Only safe HTTP status and known Google reason codes enter logs."""


def rejection(response, action):
    reason = 'unspecified'
    try:
        for detail in response.json().get('error', {}).get('details', []):
            candidate = detail.get('reason', '')
            if candidate in {'SERVICE_DISABLED', 'ACCESS_TOKEN_SCOPE_INSUFFICIENT',
                             'IAM_PERMISSION_DENIED', 'RATE_LIMIT_EXCEEDED',
                             'API_KEY_INVALID', 'CONSUMER_INVALID'}:
                reason = candidate
                break
    except (ValueError, TypeError, AttributeError):
        pass
    return SyncRejected(f'{action}: HTTP {int(response.status_code)} ({reason})')


def snapshot(db):
    result = {}
    with db.connect() as conn:
        conn.execute('BEGIN')
        for title, table in TABLES.items():
            query = f'SELECT * FROM {table}'
            if title == 'Club_Stats':
                query += " WHERE subject_type='team'"
            query += ' ORDER BY rowid'
            cursor = conn.execute(query)
            result[title] = [[c[0] for c in cursor.description]] + [list(r) for r in cursor]
    return result


def cell(value):
    # Explicit stringValue keeps IDs exact and recap text from becoming formulas.
    if value is None:
        return {}
    if isinstance(value, bool):
        return {'userEnteredValue': {'boolValue': value}}
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError('Invalid notebook number')
        return {'userEnteredValue': {'numberValue': value}}
    text = str(value)
    if len(text) > 49000:
        text = text[:48940] + '\n[Full text remains in Pep’s database.]'
    return {'userEnteredValue': {'stringValue': text}}


def update_requests(data, metadata, updated_at):
    sheets = {s['properties']['title']: s['properties'] for s in metadata['sheets']}
    if not set(data).union({'Start Here'}).issubset(sheets):
        raise ValueError('Notebook tabs are missing; restore the original tab names')
    requests = []
    for title, rows in data.items():
        props = sheets[title]
        grid = props['gridProperties']
        row_count = max(grid['rowCount'], len(rows))
        column_count = max(grid['columnCount'], len(rows[0]))
        if row_count != grid['rowCount'] or column_count != grid['columnCount']:
            requests.append({'updateSheetProperties': {
                'properties': {'sheetId': props['sheetId'], 'gridProperties': {
                    'rowCount': row_count, 'columnCount': column_count}},
                'fields': 'gridProperties.rowCount,gridProperties.columnCount'}})
        requests.append({'updateCells': {
            'range': {'sheetId': props['sheetId'], 'startRowIndex': 0,
                      'endRowIndex': row_count, 'startColumnIndex': 0,
                      'endColumnIndex': len(rows[0])},
            'rows': [{'values': [cell(v) for v in row]} for row in rows],
            'fields': 'userEnteredValue'}})
    # Status changes in the same atomic batch as the records.
    requests.append({'updateCells': {
        'start': {'sheetId': sheets['Start Here']['sheetId'], 'rowIndex': 1, 'columnIndex': 1},
        'rows': [{'values': [cell(v)]} for v in (
            'Connected — checks for changes every two minutes', updated_at,
            'Synced from Pep’s central database. Blank tabs mean no saved records.')],
        'fields': 'userEnteredValue'}})
    return requests


class GoogleNotebook:
    def __init__(self, db, spreadsheet_id, session):
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', spreadsheet_id):
            raise ValueError('Invalid notebook spreadsheet ID')
        self.db = db
        self.session = session
        self.url = f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}'
        self.fingerprint = None

    @classmethod
    def from_environment(cls, db):
        raw = os.getenv('PEP_GOOGLE_SERVICE_ACCOUNT_JSON', '')
        sheet_id = os.getenv('PEP_NOTEBOOK_SPREADSHEET_ID', '')
        if not raw and not sheet_id:
            return None
        if not raw or not sheet_id:
            raise ValueError('Set both notebook credential and spreadsheet ID')
        info = json.loads(raw)
        if info.get('type') != 'service_account' or info.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Expected a Google service account JSON key')
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import AuthorizedSession
        credentials = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        return cls(db, sheet_id, AuthorizedSession(credentials, refresh_timeout=20))

    def sync(self):
        data = snapshot(self.db)
        digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        if digest == self.fingerprint:
            return False
        response = self.session.get(self.url, params={
            'fields': 'sheets.properties(sheetId,title,gridProperties)'}, timeout=30)
        if response.status_code != 200:
            raise rejection(response, 'read')
        now = datetime.now(timezone.utc).isoformat()
        payload = {'requests': update_requests(data, response.json(), now)}
        if len(json.dumps(payload).encode()) > 8_000_000:
            raise ValueError('Notebook is too large for a single safe sync')
        response = self.session.post(self.url + ':batchUpdate', json=payload, timeout=60)
        if response.status_code != 200:
            raise rejection(response, 'write')
        self.fingerprint = digest
        self.db.set_setting('notebook_last_synced_at', now)
        log.info('Pep notebook synced: matches=%s reports=%s',
                 len(data['Matches']) - 1, len(data['Reports']) - 1)
        return True

    async def run(self, bot):
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await asyncio.to_thread(self.sync)
            except Exception as error:
                # Never print credentials, tokens, Google responses or recap text.
                log.error('Pep notebook sync failed: %s',
                          str(error) if isinstance(error, SyncRejected) else type(error).__name__)
            await asyncio.sleep(120)
