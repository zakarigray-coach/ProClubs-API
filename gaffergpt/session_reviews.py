"""Persist one review notification per completed recap session."""
from datetime import datetime, timedelta, timezone


class SessionReviews:
    def __init__(self, db, quiet_minutes=60):
        self.db = db
        self.quiet_minutes = quiet_minutes

    def matches(self, batch_id):
        return self.db.rows('''SELECT m.* FROM session_review_matches s
            JOIN matches m USING(match_id) WHERE s.batch_id=? ORDER BY m.match_id''', (batch_id,))

    def prepare(self, now, force=False):
        # Finish an interrupted send before opening another batch.
        existing = self.db.one("SELECT * FROM session_reviews WHERE message_id IS NULL ORDER BY batch_id LIMIT 1")
        if existing:
            return existing
        with self.db.connect() as conn:
            rows = conn.execute('''SELECT * FROM matches m WHERE match_type='Unknown'
                AND review_message_id IS NULL AND NOT EXISTS
                (SELECT 1 FROM session_review_matches s WHERE s.match_id=m.match_id)
                ORDER BY match_id''').fetchall()
            if not rows:
                return None
            latest = conn.execute("SELECT MAX(detected_at) FROM matches WHERE match_type!='Ignored'").fetchone()[0]
            if not force and now < datetime.fromisoformat(latest) + timedelta(minutes=self.quiet_minutes):
                return None
            batch_id = conn.execute('INSERT INTO session_reviews(created_at) VALUES (?)', (now.isoformat(),)).lastrowid
            conn.executemany('INSERT INTO session_review_matches VALUES (?,?)', [(batch_id, r['match_id']) for r in rows])
        return self.db.one('SELECT * FROM session_reviews WHERE batch_id=?', (batch_id,))

    async def tick(self, delivery, now=None, force=False):
        now = now or datetime.now(timezone.utc)
        batch = self.prepare(now, force)
        if not batch:
            return False
        # A footer marker recovers a send if Pep restarted before saving its ID.
        marker = f"pep:session:{batch['batch_id']}"
        message_id = await delivery.find(marker, batch['created_at'])
        if message_id is None:
            message_id = await delivery.send(batch['batch_id'], marker)
        with self.db.connect() as conn:
            conn.execute('UPDATE session_reviews SET message_id=?,sent_at=? WHERE batch_id=?',
                         (str(message_id), now.isoformat(), batch['batch_id']))
            conn.execute('''UPDATE matches SET review_message_id=? WHERE match_id IN
                (SELECT match_id FROM session_review_matches WHERE batch_id=?)''', (str(message_id), batch['batch_id']))
        return True
