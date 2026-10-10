"""Management's explicit spreadsheet requests, never guessed identity links."""
import re
from collections import Counter
from .database import utcnow


def parse_row(row):
    name = row[0] if row else ''
    user_id = row[1] if len(row) > 1 else ''
    if not isinstance(name, str) or name.startswith('='):
        return '', '', 'Use a plain player name'
    name = name.strip()
    if not name:
        return '', '', ''
    if user_id in ('', None):
        return name, '', 'Enter Discord ID'
    # Numeric cells may already have lost digits; never guess the original ID.
    if not isinstance(user_id, str) or not re.fullmatch(r'[1-9][0-9]{16,19}', user_id.strip()):
        return name, '', 'Paste the full Discord ID as text'
    user_id = user_id.strip()
    if int(user_id) >= 2**64:
        return name, '', 'Discord ID is invalid'
    return name, user_id, ''


async def process_rows(db, rows, owner_id, member_name):
    parsed = [parse_row(row) for row in rows]
    ids = Counter(uid for name, uid, error in parsed if uid and not error)
    keys = []
    for name, uid, error in parsed:
        try:
            keys.append(db.player_name_key(name)[1] if name and uid and not error else '')
        except ValueError:
            keys.append('')
    names = Counter(key for key in keys if key)
    results = []
    for (name, uid, error), key in zip(parsed, keys):
        saved_at = ''
        status = error
        if not status and name and uid:
            if not key:
                status = 'Invalid player name'
            elif ids[uid] > 1 or names[key] > 1:
                status = 'Duplicate name or ID — correct the rows'
            else:
                existing = db.player_link(uid)
                claimed = db.one('SELECT * FROM player_links WHERE name_key=?', (key,))
                if existing and existing['name_key'] == key:
                    status, saved_at = 'Linked', existing['linked_at']
                elif existing or claimed:
                    status = 'Existing link conflicts — use /setplayerlink to correct'
                else:
                    try:
                        username = await member_name(int(uid))
                    except LookupError:
                        status = 'Discord member not found in this server'
                    except Exception:
                        status = 'Cannot verify Discord member — will retry'
                    else:
                        # Atomic insert-only protects concurrent Discord corrections.
                        with db.connect() as conn:
                            now = utcnow()
                            conn.execute('INSERT OR IGNORE INTO player_links VALUES (?,?,?,?,?,?)',
                                         (uid, username, name, key, str(owner_id), now))
                            saved = conn.execute('SELECT * FROM player_links WHERE discord_user_id=?',
                                                 (uid,)).fetchone()
                            if saved and saved['name_key'] == key:
                                status, saved_at = 'Linked', saved['linked_at']
                            else:
                                status = 'Existing link conflicts — use /setplayerlink to correct'
        results.append([status, saved_at])
    return results
