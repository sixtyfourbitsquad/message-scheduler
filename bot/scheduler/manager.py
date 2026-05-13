"""
APScheduler integration: durable schedules live in PostgreSQL; jobs are ephemeral.

On every bot startup we rebuild scheduler jobs from the `schedules` table so automation
survives process restarts and VPS reboots.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.session import get_session_factory
from bot.models.failed_delivery import FailedDelivery
from bot.models.schedule import Schedule, ScheduleKind
from bot.runtime import get_application
from bot.services.channel_delivery_service import record_channel_delivery
from bot.services.content_poster import send_content_to_chat
from bot.services.prediction_engine_service import run_prediction_cycle
from bot.services.settings_service import get_or_create_settings
from bot.utils import timezones as tzutil

log = logging.getLogger(__name__)

_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_MAX_JITTER_CAP_S = 600


def _pick_schedule_content(row: Schedule) -> dict[str, Any]:
    pool = row.content_pool_json
    if isinstance(pool, list) and len(pool) > 0:
        valid = [p for p in pool if isinstance(p, dict) and p.get("type") and p.get("type") != "unsupported"]
        if valid:
            return random.choice(valid)
    return row.content_json or {}


async def _execute_schedule(schedule_id: int) -> None:
    """APScheduler entrypoint: load row, post to channel, reschedule if recurring."""
    app = get_application()
    bot = app.bot
    factory = get_session_factory()

    channel_id: int | None = None
    try:
        async with factory() as session:
            row = await session.get(Schedule, schedule_id)
            if row is None or row.paused:
                log.info("Schedule %s missing or paused — skipping", schedule_id)
                return

            settings = await get_or_create_settings(session)
            channel_id = settings.target_channel_id
            if channel_id is None:
                await _fail(session, schedule_id, None, "No target channel configured in Settings")
                await session.commit()
                return

            if row.jitter_seconds and int(row.jitter_seconds) > 0:
                cap = min(int(row.jitter_seconds), _MAX_JITTER_CAP_S)
                await asyncio.sleep(random.randint(0, cap))

            if row.use_prediction_engine:
                ok = await run_prediction_cycle(
                    bot,
                    session,
                    schedule=row,
                    channel_id=int(channel_id),
                    buttons_json=row.buttons_json,
                )
                if not ok:
                    await _fail(
                        session,
                        schedule_id,
                        channel_id,
                        "Prediction engine: no active sets or empty templates — add prediction_sets rows",
                    )
                    await session.commit()
                    return
            else:
                content = _pick_schedule_content(row)

                mid = await send_content_to_chat(
                    bot,
                    chat_id=channel_id,
                    content=content,
                    buttons_json=row.buttons_json,
                )
                if mid is None:
                    await _fail(session, schedule_id, channel_id, "Unsupported or empty content")
                    await session.commit()
                    return

            row.last_run_at = datetime.now(tz=timezone.utc)

            now_utc = datetime.now(tz=timezone.utc)
            if row.kind == ScheduleKind.once.value:
                row.next_run_at = None
            elif row.kind == ScheduleKind.daily.value and row.daily_slot_times:
                row.next_run_at = tzutil.next_daily_multi_slots_at(
                    list(row.daily_slot_times), row.timezone, after=now_utc
                )
            elif row.kind == ScheduleKind.daily.value and row.time_hhmm:
                row.next_run_at = tzutil.next_daily_at(row.time_hhmm, row.timezone, after=now_utc)
            elif row.kind == ScheduleKind.weekly.value and row.time_hhmm and row.weekday is not None:
                row.next_run_at = tzutil.next_weekday_at(
                    row.time_hhmm,
                    row.weekday,
                    row.timezone,
                    after=now_utc,
                )
            elif row.kind == ScheduleKind.interval.value and row.interval_seconds:
                row.next_run_at = now_utc + timedelta(seconds=int(row.interval_seconds))

            await record_channel_delivery(
                session,
                channel_id=int(channel_id),
                kind="schedule",
                schedule_id=int(row.id),
            )
            await session.commit()

            if row.kind == ScheduleKind.once.value:
                mgr = BotScheduler.instance()
                if mgr:
                    mgr.remove_job(schedule_id)
    except Exception as e:
        log.exception("Schedule execution failed: %s", e)
        async with factory() as session2:
            await _fail(session2, schedule_id, channel_id, repr(e))
            await session2.commit()


async def _fail(session: AsyncSession, schedule_id: int, channel_id: int | None, err: str) -> None:
    session.add(
        FailedDelivery(
            context="schedule",
            reference_id=schedule_id,
            channel_id=channel_id,
            error=err,
        )
    )


class BotScheduler:
    """Singleton-style scheduler wrapper (one per process)."""

    _instance: "BotScheduler | None" = None

    def __init__(self, *, timezone: str = "UTC") -> None:
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        self._started = False

    @classmethod
    def instance(cls) -> "BotScheduler | None":
        return cls._instance

    @classmethod
    def configure_singleton(cls, *, timezone: str = "UTC") -> "BotScheduler":
        cls._instance = BotScheduler(timezone=timezone)
        return cls._instance

    def start(self) -> None:
        if not self._started:
            self.scheduler.start()
            self._started = True

    def shutdown(self, *, wait: bool = True) -> None:
        if self._started:
            self.scheduler.shutdown(wait=wait)
            self._started = False

    def remove_job(self, schedule_id: int) -> None:
        prefix = f"sch_{schedule_id}"
        for job in list(self.scheduler.get_jobs()):
            jid = job.id
            if jid == prefix or jid.startswith(prefix + "_"):
                self.scheduler.remove_job(jid)

    async def reload_from_db(self) -> None:
        """Rebuild all jobs from PostgreSQL (call after startup and after schedule edits)."""
        factory = get_session_factory()
        async with factory() as session:
            res = await session.execute(select(Schedule).where(Schedule.paused.is_(False)))
            rows = list(res.scalars().all())

        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("sch_"):
                self.scheduler.remove_job(job.id)

        for row in rows:
            self._add_job_for_row(row)

    def _add_job_for_row(self, row: Schedule) -> None:
        now = datetime.now(tz=timezone.utc)
        base_id = f"sch_{row.id}"

        if row.kind == ScheduleKind.once.value:
            if not row.next_run_at:
                return
            trigger = DateTrigger(run_date=row.next_run_at)
            self.scheduler.add_job(
                _execute_schedule,
                trigger=trigger,
                id=base_id,
                kwargs={"schedule_id": row.id},
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=300,
            )
            return

        if row.kind == ScheduleKind.daily.value and row.daily_slot_times:
            slots = [s.strip() for s in row.daily_slot_times if s and ":" in str(s)]
            if not slots:
                log.warning("Schedule %s has empty daily_slot_times — skipping", row.id)
                return
            for idx, hm in enumerate(slots):
                hh, mm = str(hm).split(":", 1)
                trigger = CronTrigger(
                    hour=int(hh),
                    minute=int(mm),
                    second=0,
                    timezone=row.timezone,
                )
                self.scheduler.add_job(
                    _execute_schedule,
                    trigger=trigger,
                    id=f"{base_id}_{idx}",
                    kwargs={"schedule_id": row.id},
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=300,
                )
            return

        if row.kind == ScheduleKind.daily.value and row.time_hhmm:
            hh, mm = row.time_hhmm.split(":", 1)
            trigger = CronTrigger(
                hour=int(hh),
                minute=int(mm),
                second=0,
                timezone=row.timezone,
            )
        elif row.kind == ScheduleKind.weekly.value and row.time_hhmm and row.weekday is not None:
            hh, mm = row.time_hhmm.split(":", 1)
            dow = _DOW[int(row.weekday) % 7]
            trigger = CronTrigger(
                day_of_week=dow,
                hour=int(hh),
                minute=int(mm),
                second=0,
                timezone=row.timezone,
            )
        elif row.kind == ScheduleKind.interval.value and row.interval_seconds:
            trigger = IntervalTrigger(seconds=int(row.interval_seconds), start_date=now)
        else:
            log.warning("Schedule %s has invalid configuration — skipping job", row.id)
            return

        self.scheduler.add_job(
            _execute_schedule,
            trigger=trigger,
            id=base_id,
            kwargs={"schedule_id": row.id},
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )

    def upsert_job(self, row: Schedule) -> None:
        """Add/replace a single job after UI changes."""
        self.remove_job(row.id)
        if row.paused:
            return
        self._add_job_for_row(row)
