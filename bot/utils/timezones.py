"""Timezone helpers using `zoneinfo` (tzdata on Windows)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(tz=ZoneInfo(tz_name))


def combine_local_date_time(local_date, hhmm: str, tz_name: str) -> datetime:
    """Build timezone-aware UTC datetime from local calendar date + 'HH:MM'."""
    h, m = [int(x) for x in hhmm.split(":", 1)]
    tz = ZoneInfo(tz_name)
    naive = datetime.combine(local_date, time(hour=h, minute=m))
    return naive.replace(tzinfo=tz).astimezone(ZoneInfo("UTC"))


def next_weekday_at(hhmm: str, weekday: int, tz_name: str, *, after: datetime | None = None) -> datetime:
    """
    Next occurrence of `weekday` (0=Monday..6=Sunday) at local `HH:MM` in `tz_name`.

    Returned in UTC for storage / APScheduler.
    """
    after = after or datetime.now(tz=ZoneInfo("UTC"))
    local = after.astimezone(ZoneInfo(tz_name)).date()
    tz = ZoneInfo(tz_name)
    h, m = [int(x) for x in hhmm.split(":", 1)]
    for delta in range(0, 8):
        d = local + timedelta(days=delta)
        if d.weekday() != weekday:
            continue
        candidate = datetime.combine(d, time(hour=h, minute=m)).replace(tzinfo=tz)
        if candidate.astimezone(ZoneInfo("UTC")) > after.astimezone(ZoneInfo("UTC")):
            return candidate.astimezone(ZoneInfo("UTC"))
    # Fallback: jump a week
    d = local + timedelta(days=7)
    candidate = datetime.combine(d, time(hour=h, minute=m)).replace(tzinfo=tz)
    return candidate.astimezone(ZoneInfo("UTC"))


def next_daily_at(hhmm: str, tz_name: str, *, after: datetime | None = None) -> datetime:
    """Next local midnight crossing schedule for daily time."""
    after = after or datetime.now(tz=ZoneInfo("UTC"))
    tz = ZoneInfo(tz_name)
    local_now = after.astimezone(tz)
    h, m = [int(x) for x in hhmm.split(":", 1)]
    today = local_now.date()
    candidate_local = datetime.combine(today, time(hour=h, minute=m)).replace(tzinfo=tz)
    if candidate_local <= local_now:
        candidate_local += timedelta(days=1)
    return candidate_local.astimezone(ZoneInfo("UTC"))
