"""Dump OpenAI token/cost estimates and response times when a LiveKit session ends."""

from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PER_MILLION = 1_000_000
_LOG_DIR = Path("logs")
_DUMPED_JOBS: set[str] = set()
_TRACKERS: dict[str, SessionUsageTracker] = {}

# Published OpenAI rates (USD). Estimates only — not billed amounts.
# Text/audio/image rates are per 1M tokens. Character rates are per 1M chars.
@dataclass(frozen=True)
class ModelRates:
    input: float = 0.0
    cached_input: float = 0.0
    output: float = 0.0
    input_text: float = 0.0
    output_text: float = 0.0
    input_audio: float = 0.0
    cached_input_audio: float = 0.0
    output_audio: float = 0.0
    input_image: float = 0.0
    cached_input_image: float = 0.0
    per_million_chars: float = 0.0
    per_minute_audio: float = 0.0


_RATES: dict[str, ModelRates] = {
    "gpt-4.1": ModelRates(input=2.00, cached_input=0.50, output=8.00),
    "gpt-realtime-2.1-mini": ModelRates(
        input=0.60,
        cached_input=0.06,
        output=2.40,
        input_text=0.60,
        output_text=2.40,
        input_audio=10.00,
        cached_input_audio=0.30,
        output_audio=20.00,
        input_image=0.80,
        cached_input_image=0.08,
    ),
    "gpt-realtime-mini": ModelRates(
        input=0.60,
        cached_input=0.06,
        output=2.40,
        input_text=0.60,
        output_text=2.40,
        input_audio=10.00,
        cached_input_audio=0.30,
        output_audio=20.00,
        input_image=0.80,
        cached_input_image=0.08,
    ),
    "gpt-realtime-2.1": ModelRates(
        input=4.00,
        cached_input=0.40,
        output=24.00,
        input_text=4.00,
        output_text=24.00,
        input_audio=32.00,
        cached_input_audio=0.40,
        output_audio=64.00,
        input_image=5.00,
        cached_input_image=0.50,
    ),
    "gpt-realtime": ModelRates(
        input=4.00,
        cached_input=0.40,
        output=16.00,
        input_text=4.00,
        output_text=16.00,
        input_audio=32.00,
        cached_input_audio=0.40,
        output_audio=64.00,
        input_image=5.00,
        cached_input_image=0.50,
    ),
    "gpt-4o-transcribe": ModelRates(input=2.50, output=10.00, per_minute_audio=0.006),
    "gpt-4o-mini-transcribe": ModelRates(input=1.25, output=5.00, per_minute_audio=0.003),
    "gpt-4o-mini-tts": ModelRates(input=0.60, output=12.00),
    "tts-1-hd": ModelRates(per_million_chars=30.00),
    "tts-1": ModelRates(per_million_chars=15.00),
}

_TURN_LATENCY_KEYS = (
    "transcription_delay",
    "end_of_turn_delay",
    "on_user_turn_completed_delay",
    "llm_node_ttft",
    "tts_node_ttfb",
    "e2e_latency",
    "playback_latency",
)


def rates_for(model: str) -> ModelRates | None:
    key = (model or "").lower()
    if not key:
        return None
    if key in _RATES:
        return _RATES[key]
    for name in sorted(_RATES, key=len, reverse=True):
        if key == name or key.startswith(f"{name}-"):
            return _RATES[name]
    return None


def _tokens_cost(tokens: int, usd_per_million: float) -> float:
    return (max(tokens, 0) / _PER_MILLION) * usd_per_million


def estimate_usage_cost(usage: Any) -> float | None:
    rates = rates_for(getattr(usage, "model", "") or "")
    if rates is None:
        return None

    usage_type = getattr(usage, "type", "")
    if usage_type == "tts_usage" and rates.per_million_chars:
        chars = int(getattr(usage, "characters_count", 0) or 0)
        return (chars / _PER_MILLION) * rates.per_million_chars

    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cached = int(getattr(usage, "input_cached_tokens", 0) or 0)
    audio_in = int(getattr(usage, "input_audio_tokens", 0) or 0)
    audio_in_cached = int(getattr(usage, "input_cached_audio_tokens", 0) or 0)
    text_in = int(getattr(usage, "input_text_tokens", 0) or 0)
    text_in_cached = int(getattr(usage, "input_cached_text_tokens", 0) or 0)
    image_in = int(getattr(usage, "input_image_tokens", 0) or 0)
    image_in_cached = int(getattr(usage, "input_cached_image_tokens", 0) or 0)
    audio_out = int(getattr(usage, "output_audio_tokens", 0) or 0)
    text_out = int(getattr(usage, "output_text_tokens", 0) or 0)

    if audio_in or text_in or image_in or audio_out or text_out:
        return (
            _tokens_cost(audio_in - audio_in_cached, rates.input_audio or rates.input)
            + _tokens_cost(audio_in_cached, rates.cached_input_audio or rates.cached_input)
            + _tokens_cost(text_in - text_in_cached, rates.input_text or rates.input)
            + _tokens_cost(text_in_cached, rates.cached_input)
            + _tokens_cost(image_in - image_in_cached, rates.input_image or rates.input)
            + _tokens_cost(image_in_cached, rates.cached_input_image or rates.cached_input)
            + _tokens_cost(audio_out, rates.output_audio or rates.output)
            + _tokens_cost(text_out, rates.output_text or rates.output)
        )

    if input_tokens or output_tokens:
        return (
            _tokens_cost(input_tokens - cached, rates.input)
            + _tokens_cost(cached, rates.cached_input)
            + _tokens_cost(output_tokens, rates.output)
        )

    audio_duration = float(getattr(usage, "audio_duration", 0.0) or 0.0)
    if rates.per_minute_audio and audio_duration > 0:
        return (audio_duration / 60.0) * rates.per_minute_audio
    return None


def _fmt_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 1000:.0f}ms" if value < 1 else f"{value:.3f}s"


def _fmt_cost(value: float | None) -> str:
    if value is None:
        return "n/a (no OpenAI rate for this model)"
    return f"${value:.6f}"


def _valid_latency(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def summarize_latencies(values: list[float]) -> str:
    if not values:
        return "n/a"
    avg = statistics.fmean(values)
    return (
        f"n={len(values)} avg={_fmt_seconds(avg)} "
        f"min={_fmt_seconds(min(values))} max={_fmt_seconds(max(values))}"
    )


class SessionUsageTracker:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.started_at = time.perf_counter()
        self.plugin_samples: list[tuple[str, str, float]] = []

    def record_metrics(self, metrics: Any) -> None:
        name = type(metrics).__name__
        for field in (
            "ttft",
            "ttfb",
            "duration",
            "end_of_utterance_delay",
            "transcription_delay",
            "audio_duration",
        ):
            value = _valid_latency(getattr(metrics, field, None))
            if value is not None:
                self.plugin_samples.append((name, field, value))


def _usage_lines(model_usage: list[Any]) -> list[str]:
    lines = ["OpenAI usage (estimated from published rates, not an invoice)"]
    total = 0.0
    priced = False
    if not model_usage:
        lines.append("  (no model usage recorded)")
        return lines
    for usage in model_usage:
        provider = getattr(usage, "provider", "") or "unknown"
        model = getattr(usage, "model", "") or "unknown"
        cost = estimate_usage_cost(usage)
        lines.append(f"  {provider}/{model} [{getattr(usage, 'type', 'usage')}]")
        for field in (
            "input_tokens",
            "input_cached_tokens",
            "input_audio_tokens",
            "input_cached_audio_tokens",
            "input_text_tokens",
            "output_tokens",
            "output_audio_tokens",
            "output_text_tokens",
            "characters_count",
        ):
            value = getattr(usage, field, 0) or 0
            if value:
                lines.append(f"    {field}: {value}")
        audio_duration = float(getattr(usage, "audio_duration", 0.0) or 0.0)
        if audio_duration:
            lines.append(f"    audio_duration: {audio_duration:.3f}s")
        lines.append(f"    estimated_cost: {_fmt_cost(cost)}")
        if cost is not None:
            total += cost
            priced = True
    lines.append(f"  estimated_total: {_fmt_cost(total if priced else None)}")
    return lines


def _history_latency_lines(history: Any) -> list[str]:
    lines = ["Per-turn response times (ChatMessage.metrics)"]
    messages = []
    if history is not None:
        messages = history.messages() if callable(getattr(history, "messages", None)) else []
    if not messages:
        lines.append("  (no chat turns recorded)")
        return lines

    by_key: dict[str, list[float]] = defaultdict(list)
    turn = 0
    for item in messages:
        metrics = getattr(item, "metrics", None) or {}
        role = getattr(item, "role", "?")
        parts = []
        for key in _TURN_LATENCY_KEYS:
            value = _valid_latency(metrics.get(key) if hasattr(metrics, "get") else None)
            if value is None:
                continue
            parts.append(f"{key}={_fmt_seconds(value)}")
            by_key[key].append(value)
        if not parts:
            continue
        turn += 1
        lines.append(f"  turn {turn} [{role}]: " + ", ".join(parts))

    if turn == 0:
        lines.append("  (turns recorded, but no latency fields were populated)")
        return lines

    lines.append("  summary:")
    for key in _TURN_LATENCY_KEYS:
        if key in by_key:
            lines.append(f"    {key}: {summarize_latencies(by_key[key])}")
    return lines


def _plugin_latency_lines(tracker: SessionUsageTracker | None) -> list[str]:
    lines = ["Per-plugin response times (metrics_collected)"]
    if tracker is None or not tracker.plugin_samples:
        lines.append("  (no plugin metrics recorded)")
        return lines
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for name, field, value in tracker.plugin_samples:
        grouped[(name, field)].append(value)
    for name, field in sorted(grouped):
        lines.append(f"  {name}.{field}: {summarize_latencies(grouped[(name, field)])}")
    return lines


def format_session_report(
    *,
    kind: str,
    model_usage: list[Any],
    history: Any = None,
    tracker: SessionUsageTracker | None = None,
    reason: str = "",
    elapsed_s: float | None = None,
) -> str:
    header = [
        f"=== Mio session usage ({kind}) ===",
        f"ended_at: {datetime.now(UTC).isoformat(timespec='seconds')}",
    ]
    if reason:
        header.append(f"reason: {reason}")
    if elapsed_s is not None:
        header.append(f"session_wall_time: {elapsed_s:.1f}s")
    sections = [
        header,
        _usage_lines(model_usage),
        _history_latency_lines(history),
        _plugin_latency_lines(tracker),
    ]
    return "\n".join("\n".join(section) for section in sections) + "\n"


def _job_id(ctx: Any) -> str:
    job = getattr(ctx, "job", None)
    return str(getattr(job, "id", None) or id(ctx))


def dump_session_usage(
    ctx: Any,
    *,
    kind: str,
    session: Any = None,
    tracker: SessionUsageTracker | None = None,
    reason: str = "",
) -> Path | None:
    job_id = _job_id(ctx)
    if job_id in _DUMPED_JOBS:
        return None
    _DUMPED_JOBS.add(job_id)

    tracker = tracker or _TRACKERS.get(job_id)
    session = session or getattr(ctx, "primary_session", None)
    model_usage: list[Any] = []
    history = None
    try:
        report = ctx.make_session_report(session) if ctx is not None else None
    except (RuntimeError, AttributeError, TypeError):
        report = None
    if report is not None:
        model_usage = list(report.model_usage or [])
        history = report.chat_history
    elif session is not None:
        model_usage = list(getattr(getattr(session, "usage", None), "model_usage", []) or [])
        history = getattr(session, "history", None)

    elapsed_s = None
    if tracker is not None:
        elapsed_s = time.perf_counter() - tracker.started_at

    text = format_session_report(
        kind=kind,
        model_usage=model_usage,
        history=history,
        tracker=tracker,
        reason=reason,
        elapsed_s=elapsed_s,
    )
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _LOG_DIR / f"{kind}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.log"
    path.write_text(text)
    print(f"\n{text}Wrote session usage log to {path}\n", flush=True)
    logger.info("Wrote session usage log to %s", path)
    return path


def attach_session_usage_logging(ctx: Any, session: Any, *, kind: str) -> SessionUsageTracker:
    tracker = SessionUsageTracker(kind)
    _TRACKERS[_job_id(ctx)] = tracker

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: Any) -> None:
        tracker.record_metrics(getattr(ev, "metrics", ev))

    async def _on_shutdown(reason: str = "") -> None:
        dump_session_usage(
            ctx,
            kind=kind,
            session=session,
            tracker=tracker,
            reason=reason or "shutdown",
        )

    ctx.add_shutdown_callback(_on_shutdown)
    print(
        f"Session usage reporting on ({kind}); dump on Ctrl+C / session end.",
        flush=True,
    )
    return tracker
