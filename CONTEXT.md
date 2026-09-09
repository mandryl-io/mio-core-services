# Mio

Mio is a spoken companion. People talk out loud; Mio listens, remembers, and keeps them company.

## Language

**Core emotional experience**:
A felt moment the person is living through or remembering — grief, pride, loneliness, love, loss. What Mio stores to remember them by.
_Avoid_: fact, detail, memory (too broad)

**Medication**:
The named thing the person takes, as they would say it (for example "blood pressure tablets" or "lisinopril").
_Avoid_: drug, prescription, meds (in code and docs; "meds" is fine in speech)

**Reminder**:
A stored rule: which Medication, when, and how often. One Reminder produces many DueDoses if its Schedule is periodic.
_Avoid_: alarm, notification, job, timer

**Schedule**:
How a Reminder repeats: one-off (a single datetime) or periodic (a time of day plus a cadence), in a Zone.
_Avoid_: cron, recurrence rule, RRULE

**Zone**:
The IANA timezone a Reminder's wall-clock times belong to (for example Australia/Sydney). Due instants are still compared in UTC.
_Avoid_: tz, offset, timezone picker

**DueDose**:
One firing of a Reminder that should be spoken now. Identified by the Reminder plus the due instant.
_Avoid_: occurrence, event, alarm, notification

**Draft**:
The fields gathered so far in this conversation toward a Reminder. Not stored. Dies with the session.
_Avoid_: form, slot fill, partial reminder
