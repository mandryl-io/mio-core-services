from datetime import datetime
from zoneinfo import ZoneInfo

from mio_core_services.reminders import FakeClock, MedicationReminders

SYDNEY = ZoneInfo("Australia/Sydney")


def _book(now: datetime | None = None) -> MedicationReminders:
    clock = FakeClock(now or datetime(2026, 9, 9, 7, 0, tzinfo=SYDNEY))
    return MedicationReminders(":memory:", clock)


async def test_complete_utterance_records_a_reminder():
    book = _book()
    result = await book.set_reminder("lisinopril", "every morning at 8", None)
    assert result.status == "recorded"
    assert result.reminder_id is not None
    assert "lisinopril" in result.message.lower()


async def test_missing_medication_asks_for_the_name():
    book = _book()
    result = await book.set_reminder(None, "every morning at 8", None)
    assert result.status == "need_medication"
    assert result.reminder_id is None


async def test_missing_when_asks_for_the_time():
    book = _book()
    result = await book.set_reminder("pills", None, None)
    assert result.status == "need_when"
    assert "pills" in result.message.lower()


async def test_clock_time_without_frequency_asks_once_or_daily():
    book = _book()
    result = await book.set_reminder("pills", "at 8", None)
    assert result.status == "need_frequency"


async def test_draft_merges_later_turns():
    book = _book()
    first = await book.set_reminder("pills", None, None)
    assert first.status == "need_when"
    second = await book.set_reminder(None, "8am", None)
    assert second.status == "need_frequency"
    third = await book.set_reminder(None, None, "every day")
    assert third.status == "recorded"
    assert third.reminder_id is not None


async def test_same_medication_and_due_time_is_idempotent():
    book = _book()
    first = await book.set_reminder("lisinopril", "every morning at 8", None)
    second = await book.set_reminder("lisinopril", "every morning at 8", None)
    assert first.status == second.status == "recorded"
    assert first.reminder_id == second.reminder_id


async def test_one_off_fires_once():
    clock = FakeClock(datetime(2026, 9, 9, 8, 0, tzinfo=SYDNEY))
    book = MedicationReminders(":memory:", clock)
    result = await book.set_reminder("pills", "in 20 minutes", None)
    assert result.status == "recorded"
    assert await book.tick() is None
    clock.set(datetime(2026, 9, 9, 8, 20, tzinfo=SYDNEY))
    due = await book.tick()
    assert due is not None
    assert due.medication == "pills"
    assert due.reminder_id == result.reminder_id
    assert await book.tick() is None


async def test_periodic_rolls_forward_and_does_not_double_claim():
    clock = FakeClock(datetime(2026, 9, 9, 7, 0, tzinfo=SYDNEY))
    book = MedicationReminders(":memory:", clock)
    await book.set_reminder("lisinopril", "every morning at 8", None)
    clock.set(datetime(2026, 9, 9, 8, 0, tzinfo=SYDNEY))
    due = await book.tick()
    assert due is not None
    assert due.medication == "lisinopril"
    assert await book.tick() is None
    clock.set(datetime(2026, 9, 10, 8, 0, tzinfo=SYDNEY))
    next_due = await book.tick()
    assert next_due is not None
    assert next_due.medication == "lisinopril"


async def test_overdue_backlog_speaks_once_then_jumps_ahead():
    clock = FakeClock(datetime(2026, 9, 7, 7, 0, tzinfo=SYDNEY))
    book = MedicationReminders(":memory:", clock)
    await book.set_reminder("lisinopril", "every morning at 8", None)
    clock.set(datetime(2026, 9, 9, 10, 0, tzinfo=SYDNEY))
    first = await book.tick()
    assert first is not None
    assert await book.tick() is None
    clock.set(datetime(2026, 9, 10, 8, 0, tzinfo=SYDNEY))
    later = await book.tick()
    assert later is not None


async def test_set_handler_returns_the_spoken_sentence():
    book = _book()
    spoken: list[str] = []

    class Params:
        arguments = {"medication": "lisinopril", "when": "every morning at 8"}

        async def result_callback(self, message: str) -> None:
            spoken.append(message)

    await book.set(Params())
    assert spoken
    assert "lisinopril" in spoken[0].lower()

