from types import SimpleNamespace

from mio_core_services.session_usage import (
    SessionUsageTracker,
    dump_session_usage,
    estimate_usage_cost,
    format_session_report,
    rates_for,
    summarize_latencies,
)


def test_rates_for_matches_longest_prefix():
    assert rates_for("gpt-realtime-2.1-mini").input_audio == 10.00
    assert rates_for("gpt-realtime-2.1").output_text == 24.00
    assert rates_for("gpt-realtime").output_text == 16.00
    assert rates_for("tts-1-hd").per_million_chars == 30.00
    assert rates_for("tts-1").per_million_chars == 15.00
    assert rates_for("unknown-model") is None


def test_estimate_gpt_4_1_token_cost():
    usage = SimpleNamespace(
        type="llm_usage",
        model="gpt-4.1",
        input_tokens=1_000_000,
        input_cached_tokens=250_000,
        output_tokens=500_000,
        input_audio_tokens=0,
        input_text_tokens=0,
        input_image_tokens=0,
        output_audio_tokens=0,
        output_text_tokens=0,
        characters_count=0,
        audio_duration=0.0,
    )
    # 750k uncached * $2 + 250k cached * $0.50 + 500k out * $8
    assert estimate_usage_cost(usage) == 1.5 + 0.125 + 4.0


def test_estimate_realtime_audio_and_text_cost():
    usage = SimpleNamespace(
        type="llm_usage",
        model="gpt-realtime",
        input_tokens=0,
        input_cached_tokens=0,
        output_tokens=0,
        input_audio_tokens=1_000_000,
        input_cached_audio_tokens=250_000,
        input_text_tokens=1_000_000,
        input_cached_text_tokens=0,
        input_image_tokens=0,
        input_cached_image_tokens=0,
        output_audio_tokens=1_000_000,
        output_text_tokens=1_000_000,
        characters_count=0,
        audio_duration=0.0,
    )
    # audio: 750k*$32 + 250k*$0.40; text in $4; audio out $64; text out $16
    assert estimate_usage_cost(usage) == 24.0 + 0.1 + 4.0 + 64.0 + 16.0


def test_estimate_tts_character_cost():
    usage = SimpleNamespace(
        type="tts_usage",
        model="tts-1",
        characters_count=1_000_000,
        input_tokens=0,
        output_tokens=0,
        audio_duration=0.0,
    )
    assert estimate_usage_cost(usage) == 15.0


def test_estimate_stt_falls_back_to_audio_duration():
    usage = SimpleNamespace(
        type="stt_usage",
        model="gpt-4o-transcribe",
        input_tokens=0,
        output_tokens=0,
        audio_duration=60.0,
        characters_count=0,
        input_audio_tokens=0,
        input_text_tokens=0,
        input_image_tokens=0,
        output_audio_tokens=0,
        output_text_tokens=0,
    )
    assert estimate_usage_cost(usage) == 0.006


def test_format_session_report_includes_cost_and_latencies():
    usage = SimpleNamespace(
        type="llm_usage",
        provider="openai",
        model="gpt-4.1",
        input_tokens=1000,
        input_cached_tokens=0,
        output_tokens=200,
        input_audio_tokens=0,
        input_cached_audio_tokens=0,
        input_text_tokens=0,
        output_audio_tokens=0,
        output_text_tokens=0,
        characters_count=0,
        audio_duration=0.0,
    )
    history = SimpleNamespace(
        messages=lambda: [
            SimpleNamespace(
                role="assistant",
                metrics={"e2e_latency": 0.42, "llm_node_ttft": 0.18},
            )
        ]
    )
    tracker = SessionUsageTracker("pipeline")
    tracker.record_metrics(SimpleNamespace(ttft=0.2, duration=0.5))
    report = format_session_report(
        kind="pipeline",
        model_usage=[usage],
        history=history,
        tracker=tracker,
        reason="shutdown",
        elapsed_s=12.5,
    )
    assert "Mio session usage (pipeline)" in report
    assert "openai/gpt-4.1" in report
    assert "estimated_cost: $" in report
    assert "e2e_latency=420ms" in report
    assert "SimpleNamespace.ttft" in report
    assert "session_wall_time: 12.5s" in report


def test_dump_session_usage_writes_log_once(tmp_path, monkeypatch):
    monkeypatch.setattr("mio_core_services.session_usage._LOG_DIR", tmp_path)
    monkeypatch.setattr("mio_core_services.session_usage._DUMPED_JOBS", set())
    ctx = SimpleNamespace(
        job=SimpleNamespace(id="job-1"),
        primary_session=None,
        make_session_report=lambda session=None: (_ for _ in ()).throw(RuntimeError("no report")),
    )
    session = SimpleNamespace(
        usage=SimpleNamespace(model_usage=[]),
        history=SimpleNamespace(messages=list),
    )
    path = dump_session_usage(ctx, kind="realtime", session=session, reason="shutdown")
    assert path is not None
    assert path.read_text().startswith("=== Mio session usage (realtime) ===")
    assert dump_session_usage(ctx, kind="realtime", session=session) is None


def test_summarize_latencies_empty():
    assert summarize_latencies([]) == "n/a"
    assert "n=2" in summarize_latencies([0.1, 0.3])
