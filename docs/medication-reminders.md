# Medication reminders

On-device Reminders for Mio: set them by voice, persist them in SQLite, speak a DueDose when it is time.

This is the plan for `feat/medication-reminders`. Domain terms live in [`CONTEXT.md`](../CONTEXT.md).

## Decision

One **module**, `MedicationReminders`, wired like `RetrievalEngine`: a `FrameProcessor` plus a thin `FunctionSchema`. Two entry points. Optional tool fields. Completeness, parse, persist, and claim live behind that seam. Speech goes out as frames the pipeline already owns — no Speech port until a second delivery path exists.

V1 does not list, cancel, snooze, or record taken/skipped. Those are later methods on the same module, not a reason to widen the first cut.

## Why this shape

Four designs were run in parallel. The hybrid takes:

- From the minimal design: two entry points (`set_reminder`, `tick`), optional fields, one spoken sentence back to Mio, injected Clock.
- From the caller-first design: the house composition — `FunctionSchema` + `FrameProcessor` in `stages`, system-instruction append, same as embed knowledge.
- From the ports design: a session Draft so "eight in the morning" on the next turn still completes; tests never open a websocket (`tick` is the fire-path test surface).
- From the flexible design: DueDose identity `(reminder_id, due_at)`, at-most-one claim, and "do not speak over the user" as a later gate — not a v1 Subject union or five LLM tools.

Rejected as-is:

- Minimal without a Draft: older users answer one field per turn; Realtime often will not re-pass earlier slots.
- Caller-first required fields: Realtime is worse than chat at "do not call until complete". The tool should accept whatever was just said.
- Ports `Speech` protocol: this repo already tests processors by calling a method and asserting frames (`attach_context`). A second speak-callback is a hypothetical seam until we have client-side chime or local TTS.
- Flexible `ReminderBook`: list/cancel/change/snooze/taken are real, and they wait. A Subject union before a second kind is a hypothetical seam.

## Interface

```python
class MedicationReminders(FrameProcessor):
    def __init__(self, sqlite_path: str, clock: Clock) -> None: ...

    async def set_reminder(
        self,
        medication: str | None = None,
        when: str | None = None,
        frequency: str | None = None,
    ) -> SetReminderResult: ...

    async def tick(self) -> DueDose | None: ...
```

`SetReminderResult.status` is `recorded | need_medication | need_when | need_frequency | failed`. `message` is always one spoken sentence. Persist only on `recorded`.

`tick` claims at most one DueDose with `next_due <= clock.now()` (oldest first), rolls a periodic Reminder forward, and finishes a one-off. Returns `None` if nothing is due. Does not raise.

Clock is a real seam (`SystemClock` / `FakeClock`). SQLite is not: pass a file path, or `":memory:"` in tests, on the same instance.

### Tool adapter

`SetMedicationReminderTool` matches `EmbedKnowledgeTool`: schema only, handler injected. All three properties optional. Description: call with whatever the user said; do not invent a name, time, or frequency; after the tool returns, say that sentence and wait.

### Conversation

- Complete utterance ("remind me to take my lisinopril every morning at eight") → one tool call → `recorded` → brief confirm.
- Incomplete → tool call with what is known → `need_*` → Mio asks that one thing. Infer frequency when `when` already encodes it ("every morning at 8"). Do not ask.
- Session Draft merges later turns. "Pills" then "eight am" then "every day" becomes one Reminder. Draft never hits SQLite.

### Trigger

Not a second service. The poller is an asyncio loop **inside** `MedicationReminders`, which is already in the `MioPipeline` process.

`make run-conversation-service` starts `main.py` (the pipeline) and the client. When that pipeline starts, the processor starts; when the processor starts, it loops `tick`. Kill the make target and the poller dies with it. No extra Makefile target, no sidecar process, no IPC.

A separate poller would still need the live Realtime session to speak a DueDose. That session only exists in this process. Splitting it out now would invent a Speech port we do not have. If reminders later must fire when Mio is closed, that is a new delivery path (OS alarm or a background worker plus a chime) — not this cut.

On `StartFrame`, the loop calls `tick`. When a DueDose is claimed, it appends a developer line to the live `LLMContext` and pushes `InputTextRawFrame` so Mio speaks one short sentence, then waits. If the greeting has not run, hold the claim until context exists.

Poll interval stays inside the implementation (~15s). Tests call `tick` with a frozen clock; they do not sleep.

Process restart: `next_due_at` lives in SQLite, so a due Reminder is still due after reboot of the same app. Claim is an atomic `UPDATE`. Overdue backlog: speak once, then jump to the next future slot — do not dump missed doses.

## SQLite (internal)

One table. A DueDose is a claimed `next_due_at`, not a second table.

```sql
reminders (
  id TEXT PRIMARY KEY,
  medication TEXT NOT NULL,
  schedule_kind TEXT NOT NULL, -- one_off | periodic
  period TEXT,                 -- daily | weekly | every_n_hours, null if one-off
  timezone TEXT NOT NULL,     -- IANA, e.g. Australia/Sydney
  next_due_at TEXT NOT NULL,   -- UTC ISO
  completed INTEGER NOT NULL DEFAULT 0
)
```

`timezone` is the zone wall-clock times belong to. `next_due_at` stays UTC so `tick` compares `clock.now()` without loading zones. Periodic roll-forward uses `timezone` so "every day at 8am" stays 8am across DST.

Mio does not ask for a timezone. Default is the zone on `clock.now()` at `recorded`. A later "I'm in Melbourne now" is a change-Reminder feature, not v1 collection.

Several Reminders may share a Medication name ("lisinopril at 8am" and "lisinopril at 8pm" are two rows). Same name plus same `next_due_at` is idempotent.

No repository port. File vs `:memory:` is substitution, not two adapters.

## Pipeline wiring

Same three lines as knowledge, twice:

1. Construct `MedicationReminders(sqlite_path, clock)`.
2. `SetMedicationReminderTool(reminders.set)` on `LLMContext.tools`.
3. Drop the processor in `stages` after the user aggregator and before the LLM.

`MioPipelineConfig` grows `clock` and `reminder_db_path`. `main.py` passes a file path. Evals pass `":memory:"` and a `FakeClock` when they need a due firing.

## What v1 does not include

List, cancel, change, snooze, taken vs skipped, asking the person for a timezone, OS-level alarms, a second poller process, a Speech port, a generic "reminder" Subject for non-medication.

When cancel lands, it is a second tool on the same processor. When a client chime exists, that is when to open a Speech port.

## Build order

1. `MedicationReminders` with `set_reminder` + in-memory SQLite + `FakeClock`. Tests: complete set, one missing field, inferred frequency, Draft across calls, idempotent same-name-and-time.
2. `tick`: one-off fires once; periodic rolls forward; second `tick` at the same `now` returns `None`; overdue backlog speaks once.
3. `SetMedicationReminderTool` + pipeline composition + system-instruction append.
4. Processor poll + `LLMRunFrame` kick. One eval: complete utterance. One eval: missing time, then complete.

## Tests

The interface is the test surface. Assert `SetReminderResult` and `DueDose`. Do not assert on table contents.

Eval scenarios (Pipecat evals, not pytest): one complete set; one multi-turn collection. Judge hears a brief confirm, not an interrogation when the user already gave everything.
