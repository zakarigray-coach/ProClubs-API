"""Reporting week boundaries in Eastern Time."""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo

ET=ZoneInfo('America/New_York')


def week_window(now):
    local=now.astimezone(ET)
    monday=local.date()-timedelta(days=local.weekday())
    start=datetime.combine(monday,time(),ET)
    end=datetime.combine(monday+timedelta(days=7),time(),ET)
    return start.astimezone(timezone.utc).isoformat(),end.astimezone(timezone.utc).isoformat()
