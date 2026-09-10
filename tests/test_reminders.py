import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from pipecat.frames.frames import InputTextRawFrame, LLMRunFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from mio_core_services.reminders import DueDose, FakeClock, MedicationReminders

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


async def test_spoken_in_two_minutes_records_and_fires():
    clock = FakeClock(datetime(2026, 9, 9, 8, 0, tzinfo=SYDNEY))
    book = MedicationReminders(":memory:", clock)
    result = await book.set_reminder("Diabex 1000 milligrams", "in two minutes", None)
    assert result.status == "recorded"
    clock.set(datetime(2026, 9, 9, 8, 2, tzinfo=SYDNEY))
    due = await book.tick()
    assert due is not None
    assert due.medication == "Diabex 1000 milligrams"


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


async def test_due_dose_queues_text_the_realtime_llm_will_run():
    book = _book()
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    book.push_frame = capture
    book._context = LLMContext([])
    await book._kick_due(
        DueDose(
            reminder_id="abc",
            medication="Diapex",
            due_at=datetime(2026, 9, 9, 8, 2, tzinfo=SYDNEY),
        )
    )
    assert not any(isinstance(frame, LLMRunFrame) for frame in pushed)
    assert any(
        isinstance(frame, InputTextRawFrame) and "Diapex" in frame.text
        for frame in pushed
    )


async def test_poll_loop_kicks_when_the_clock_reaches_due():
    clock = FakeClock(datetime(2026, 9, 9, 8, 0, tzinfo=SYDNEY))
    book = MedicationReminders(":memory:", clock, poll_interval=0.05)
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    book.push_frame = capture
    book._context = LLMContext([])
    await book.set_reminder("Diapex", "in two minutes", None)
    book._poll_task = asyncio.create_task(book._poll())
    clock.set(datetime(2026, 9, 9, 8, 2, tzinfo=SYDNEY))
    try:
        for _ in range(20):
            if any(
                isinstance(frame, InputTextRawFrame) and "Diapex" in frame.text
                for frame in pushed
            ):
                break
            await asyncio.sleep(0.05)
        assert any(
            isinstance(frame, InputTextRawFrame) and "Diapex" in frame.text
            for frame in pushed
        )
    finally:
        await book.cleanup()


