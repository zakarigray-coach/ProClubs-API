"""Persisted Friday jobs with leases, delivery reconciliation and catch-up."""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo

ET=ZoneInfo('America/New_York')


def week_window(now):
    local=now.astimezone(ET)
    monday=local.date()-timedelta(days=local.weekday())
    start=datetime.combine(monday,time(),ET)
    end=datetime.combine(monday+timedelta(days=7),time(),ET)
    return start.astimezone(timezone.utc).isoformat(),end.astimezone(timezone.utc).isoformat()


def friday_due(start):
    local=datetime.fromisoformat(start).astimezone(ET)
    return datetime.combine(local.date()+timedelta(days=4),time(8),ET).astimezone(timezone.utc)


class WeeklyScheduler:
    def __init__(self, db, owner, delivery):
        self.db=db; self.owner=str(owner); self.delivery=delivery

    def seed(self, now):
        first=self.db.setting('scheduler_first_week')
        if first is None:
            first=week_window(now)[0]
            self.db.set_setting('scheduler_first_week',first)
        start=datetime.fromisoformat(first).astimezone(ET)
        last=datetime.fromisoformat(week_window(now)[0]).astimezone(ET)
        while start<=last:
            a,b=week_window(start)
            report=self.db.open_report(a,b,self.owner)
            key=f'weekly:{self.owner}:{start.date().isoformat()}'
            self.db.execute('INSERT OR IGNORE INTO weekly_jobs(job_key,report_id,due_at) VALUES (?,?,?)',
                (key,report['report_id'],friday_due(a).isoformat()))
            start=datetime.combine(start.date()+timedelta(days=7),time(),ET)

    async def tick(self, now):
        self.seed(now)
        for job in self.db.rows("SELECT * FROM weekly_jobs WHERE job_key LIKE 'weekly:%' AND state IN ('pending','sending') AND due_at<=? ORDER BY due_at",(now.isoformat(),)):
            await self._deliver(job,now,False)
        for job in self.db.rows("SELECT * FROM weekly_jobs WHERE state='sent' AND reminder_at IS NOT NULL AND reminder_at<=? AND reminder_sent_at IS NULL",(now.isoformat(),)):
            await self._deliver(job,now,True)

    async def _deliver(self, job, now, reminder):
        # Atomic claim makes overlapping ticks/processes harmless.
        with self.db.connect() as conn:
            cur=conn.execute('''UPDATE weekly_jobs SET lease_until=?,state=CASE WHEN ? THEN state ELSE 'sending' END,
             attempts=attempts+1 WHERE job_key=? AND state!= 'skipped' AND (lease_until IS NULL OR lease_until<=?)''',
             ((now+timedelta(minutes=5)).isoformat(),int(reminder),job['job_key'],now.isoformat()))
            if not cur.rowcount:
                return
        marker=job['job_key']+(f":reminder:{job['reminder_at']}" if reminder else ':prompt')
        try:
            # If Discord accepted the message before a crash, find it instead of resending.
            message_id=await self.delivery.find(marker)
            if message_id is None:
                message_id=await self.delivery.send(job['report_id'],marker)
            if reminder:
                self.db.execute('UPDATE weekly_jobs SET reminder_sent_at=?,lease_until=NULL,last_error=NULL WHERE job_key=?',(now.isoformat(),job['job_key']))
            else:
                self.db.execute("UPDATE weekly_jobs SET state='sent',sent_at=?,message_id=?,lease_until=NULL,last_error=NULL WHERE job_key=?",(now.isoformat(),str(message_id),job['job_key']))
        except Exception as error:
            # Keep lease as retry backoff; never log tokens or recap content.
            self.db.execute('UPDATE weekly_jobs SET last_error=? WHERE job_key=?',(type(error).__name__,job['job_key']))

    def remind(self, report_id, now, minutes=60):
        if self.db.report(report_id)['status']=='skipped':
            raise ValueError('This week was skipped.')
        self.db.execute('''UPDATE weekly_jobs SET reminder_at=?,reminder_sent_at=NULL,lease_until=NULL
         WHERE report_id=? AND state='sent' AND job_key LIKE 'weekly:%' ''',((now+timedelta(minutes=minutes)).isoformat(),report_id))

    def schedule_test(self, now):
        report=self.db.open_report(*week_window(now),self.owner)
        key=f'test:{self.owner}:{now.isoformat()}'
        self.db.execute('INSERT INTO weekly_jobs(job_key,report_id,due_at) VALUES (?,?,?)',
                        (key,report['report_id'],(now+timedelta(minutes=1)).isoformat()))
        return key

    async def tick_tests(self, now):
        for job in self.db.rows("SELECT * FROM weekly_jobs WHERE job_key LIKE 'test:%' AND state IN ('pending','sending') AND due_at<=?",(now.isoformat(),)):
            await self._deliver(job,now,False)

    def skip(self, report_id):
        with self.db.connect() as conn:
            conn.execute("UPDATE weekly_jobs SET state='skipped',reminder_at=NULL,lease_until=NULL WHERE report_id=?",(report_id,))
            conn.execute("UPDATE weekly_reports SET status='skipped' WHERE report_id=?",(report_id,))
