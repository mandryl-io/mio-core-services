"""On-device medication Reminders. Completeness, persist, and claim live here."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputTextRawFrame,
    LLMContextFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

SetStatus = Literal[
    "recorded",
    "need_medication",
    "need_when",
    "need_frequency",
    "failed",
]


class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware instant."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


class FakeClock:
    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = now


@dataclass(frozen=True)
class SetReminderResult:
    status: SetStatus
    message: str
    reminder_id: str | None = None


@dataclass(frozen=True)
class DueDose:
    reminder_id: str
    medication: str
    due_at: datetime


@dataclass(frozen=True)
class _DueReminder:
    id: str
    medication: str
    schedule_kind: str
    period: str | None
    timezone: str
    due_at: datetime


@dataclass
class _Draft:
    medication: str | None = None
    when: str | None = None
    frequency: str | None = None


_WORD_QUANTITIES = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
}
_QUANTITY = r"(?:\d+|" + "|".join(sorted(_WORD_QUANTITIES, key=len, reverse=True)) + r")"
_IN_MINUTES = re.compile(rf"\bin\s+({_QUANTITY})\s+minutes?\b", re.I)
_IN_HOURS = re.compile(rf"\bin\s+({_QUANTITY})\s+hours?\b", re.I)
_CLOCK_TIME = re.compile(
    r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.I,
)

_PERIODIC_HINTS = (
    "every",
    "daily",
    "each day",
    "each morning",
    "each evening",
)
_ONCE_HINTS = ("once", "one-off", "one off", "one time", "just once")


class MedicationReminders(FrameProcessor):
    """Store Reminders and claim DueDoses. Place before the LLM."""

    def __init__(
        self,
        sqlite_path: str,
        clock: Clock,
        *,
        poll_interval: float = 15.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._wall_clock = clock
        self._poll_interval = poll_interval
        self._db = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                medication TEXT NOT NULL,
                schedule_kind TEXT NOT NULL,
                period TEXT,
                timezone TEXT NOT NULL,
                next_due_at TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS reminders_due "
            "ON reminders (completed, next_due_at)"
        )
        self._db.commit()
        self._draft = _Draft()
        self._context = None
        self._poll_task = None
        self._pending_due: DueDose | None = None

    async def set_reminder(
        self,
        medication: str | None = None,
        when: str | None = None,
        frequency: str | None = None,
    ) -> SetReminderResult:
        try:
            return self._set_reminder(medication, when, frequency)
        except Exception:
            logger.exception("reminders: failed to set reminder")
            return SetReminderResult(
                status="failed",
                message="I could not save that reminder. Let's try again in a moment.",
            )

    async def set(self, params) -> None:
        result = await self.set_reminder(
            medication=params.arguments.get("medication") or None,
            when=params.arguments.get("when") or None,
            frequency=params.arguments.get("frequency") or None,
        )
        await params.result_callback(result.message)

    async def tick(self) -> DueDose | None:
        try:
            return self._tick()
        except Exception:
            logger.exception("reminders: tick failed")
            return None

    def _set_reminder(
        self,
        medication: str | None,
        when: str | None,
        frequency: str | None,
    ) -> SetReminderResult:
        self._merge_draft(medication, when, frequency)
        if not self._draft.medication:
            return SetReminderResult(
                status="need_medication",
                message="What medication should I remind you about?",
            )
        if not self._draft.when:
            return SetReminderResult(
                status="need_when",
                message=(
                    f"When should I remind you to take your {self._draft.medication}?"
                ),
            )
        parsed = _parse_schedule(
            self._draft.when,
            self._draft.frequency,
            self._wall_clock.now(),
        )
        if parsed == "need_when":
            return SetReminderResult(
                status="need_when",
                message=(
                    f"When should I remind you to take your {self._draft.medication}?"
                ),
            )
        if parsed == "need_frequency":
            return SetReminderResult(
                status="need_frequency",
                message="Should I remind you once, or every day?",
            )
        kind, period, due_at, spoken_when = parsed
        tz_name = _zone_name(self._wall_clock.now())
        due_iso = due_at.astimezone(timezone.utc).isoformat()
        existing = self._db.execute(
            "SELECT id FROM reminders "
            "WHERE lower(medication) = lower(?) AND next_due_at = ? AND completed = 0",
            (self._draft.medication, due_iso),
        ).fetchone()
        if existing:
            reminder_id = existing["id"]
        else:
            reminder_id = uuid.uuid4().hex
            self._db.execute(
                "INSERT INTO reminders "
                "(id, medication, schedule_kind, period, timezone, next_due_at, completed) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    reminder_id,
                    self._draft.medication,
                    kind,
                    period,
                    tz_name,
                    due_iso,
                ),
            )
            self._db.commit()
        name = self._draft.medication
        self._draft = _Draft()
        return SetReminderResult(
            status="recorded",
            message=f"I'll remind you to take your {name} {spoken_when}.",
            reminder_id=reminder_id,
        )

    def _merge_draft(
        self,
        medication: str | None,
        when: str | None,
        frequency: str | None,
    ) -> None:
        if medication and medication.strip():
            self._draft.medication = medication.strip()
        if when and when.strip():
            self._draft.when = when.strip()
        if frequency and frequency.strip():
            self._draft.frequency = frequency.strip()

    def _reminders_due_before(
        self,
        before: datetime,
        tz: tzinfo | None = None,
        *,
        limit: int = 1,
    ) -> list[_DueReminder]:
        zone = tz or before.tzinfo or timezone.utc
        before_utc = before.astimezone(timezone.utc).isoformat()
        rows = self._db.execute(
            "SELECT * FROM reminders "
            "WHERE completed = 0 AND next_due_at <= ? "
            "ORDER BY next_due_at ASC LIMIT ?",
            (before_utc, limit),
        ).fetchall()
        due: list[_DueReminder] = []
        for row in rows:
            due_at = datetime.fromisoformat(row["next_due_at"])
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            due.append(
                _DueReminder(
                    id=row["id"],
                    medication=row["medication"],
                    schedule_kind=row["schedule_kind"],
                    period=row["period"],
                    timezone=row["timezone"],
                    due_at=due_at.astimezone(zone),
                )
            )
        return due

    def _tick(self) -> DueDose | None:
        now = self._wall_clock.now()
        due = self._reminders_due_before(now)
        if not due:
            return None
        row = due[0]
        if row.schedule_kind == "one_off":
            self._db.execute(
                "UPDATE reminders SET completed = 1 WHERE id = ?",
                (row.id,),
            )
        else:
            nxt = _next_future_due(
                row.due_at,
                row.period,
                ZoneInfo(row.timezone),
                now,
            )
            self._db.execute(
                "UPDATE reminders SET next_due_at = ? WHERE id = ?",
                (nxt.astimezone(timezone.utc).isoformat(), row.id),
            )
        self._db.commit()
        return DueDose(
            reminder_id=row.id,
            medication=row.medication,
            due_at=row.due_at,
        )

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, StartFrame):
            try:
                self._poll_task = self.create_task(
                    self._poll(), name="medication_poll"
                )
            except Exception:
                self._poll_task = asyncio.create_task(self._poll())
        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_poll()
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            self._context = frame.context
            if self._pending_due is not None:
                await self._kick_due(self._pending_due)
                self._pending_due = None
        await self.push_frame(frame, direction)

    async def _poll(self) -> None:
        while True:
            try:
                due = await self.tick()
                if due is not None:
                    if self._context is None:
                        self._pending_due = due
                        logger.info(
                            "reminders: holding DueDose for %s until context exists",
                            due.medication,
                        )
                    else:
                        await self._kick_due(due)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reminders: poll iteration failed")
            await asyncio.sleep(self._poll_interval)

    async def cleanup(self):
        await self._stop_poll()
        await super().cleanup()

    async def _kick_due(self, due: DueDose) -> None:
        if self._context is None:
            self._pending_due = due
            return
        instruction = (
            "A DueDose is due. In one short sentence, tell them it is time "
            f"for {due.medication}. Then wait. Do not list other reminders."
        )
        self._context.add_message({"role": "developer", "content": instruction})
        logger.info("reminders: kicking realtime for %s", due.medication)
        await self.push_frame(
            InputTextRawFrame(text=instruction), FrameDirection.DOWNSTREAM
        )

    async def _stop_poll(self) -> None:
        if self._poll_task is None:
            return
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        self._poll_task = None


def _zone_name(now: datetime) -> str:
    tz = now.tzinfo
    if tz is None:
        return "UTC"
    name = getattr(tz, "key", None)
    if name:
        return name
    return "UTC"


def _parse_schedule(
    when: str,
    frequency: str | None,
    now: datetime,
) -> tuple[str, str | None, datetime, str] | Literal["need_when", "need_frequency"]:
    blob = f"{when} {frequency or ''}".lower()
    periodic = _is_periodic(when, frequency)
    relative = _relative_due(when, now)
    if relative is not None:
        return ("one_off", None, relative, _spoken_relative(when))
    hour_minute = _parse_clock_time(when)
    if hour_minute is None and "morning" in blob:
        hour_minute = (8, 0)
    if hour_minute is None:
        return "need_when"
    if periodic is None:
        return "need_frequency"
    hour, minute = hour_minute
    tz = now.tzinfo or timezone.utc
    due = _next_wall_clock(now, hour, minute, tz)
    spoken = _spoken_clock(hour, minute, periodic)
    if periodic:
        return ("periodic", "daily", due, spoken)
    return ("one_off", None, due, spoken)


def _is_periodic(when: str, frequency: str | None) -> bool | None:
    blob = f"{when} {frequency or ''}".lower()
    if any(hint in blob for hint in _ONCE_HINTS):
        return False
    if any(hint in blob for hint in _PERIODIC_HINTS):
        return True
    if frequency and frequency.strip():
        return False
    return None


def _parse_quantity(raw: str) -> int | None:
    text = raw.strip().lower()
    if text.isdigit():
        return int(text)
    return _WORD_QUANTITIES.get(text)


def _relative_due(when: str, now: datetime) -> datetime | None:
    minutes = _IN_MINUTES.search(when)
    if minutes:
        n = _parse_quantity(minutes.group(1))
        if n is not None:
            return now + timedelta(minutes=n)
    hours = _IN_HOURS.search(when)
    if hours:
        n = _parse_quantity(hours.group(1))
        if n is not None:
            return now + timedelta(hours=n)
    return None


def _spoken_relative(when: str) -> str:
    minutes = _IN_MINUTES.search(when)
    if minutes:
        n = _parse_quantity(minutes.group(1))
        if n is not None:
            unit = "minute" if n == 1 else "minutes"
            return f"in {n} {unit}"
    hours = _IN_HOURS.search(when)
    if hours:
        n = _parse_quantity(hours.group(1))
        if n is not None:
            unit = "hour" if n == 1 else "hours"
            return f"in {n} {unit}"
    return when


def _parse_clock_time(when: str) -> tuple[int, int] | None:
    match = _CLOCK_TIME.search(when)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").lower()
    if hour > 24 or minute > 59:
        return None
    blob = when.lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif not ampm and hour <= 12:
        if any(word in blob for word in ("evening", "night", "afternoon")):
            if hour < 12:
                hour += 12
        elif "morning" in blob and hour == 12:
            hour = 0
    if hour == 24:
        return None
    return hour, minute


def _next_wall_clock(now: datetime, hour: int, minute: int, tz) -> datetime:
    local = now.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return candidate


def _spoken_clock(hour: int, minute: int, periodic: bool) -> str:
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    time = f"{display}:{minute:02d} {suffix}" if minute else f"{display} {suffix}"
    if periodic:
        return f"every day at {time}"
    return f"at {time}"


def _next_future_due(
    claimed: datetime,
    period: str | None,
    tz: ZoneInfo,
    now: datetime,
) -> datetime:
    nxt = claimed.astimezone(tz) + timedelta(days=1)
    now_local = now.astimezone(tz)
    while nxt <= now_local:
        nxt = nxt + timedelta(days=1)
    return nxt
