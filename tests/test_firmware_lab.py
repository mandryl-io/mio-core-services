import json
from http.client import HTTPConnection
from threading import Thread
from types import SimpleNamespace

import pytest
from http.server import ThreadingHTTPServer

from devtools.firmware_lab.app import FirmwareLabHandler

from devtools.firmware_lab.catalog import TOOLS, WORKFLOWS, get_tool, get_workflow
from devtools.firmware_lab.commands import argv_for_step, build_argv, command_line
from devtools.firmware_lab.runner import ALLOWED_MODULES, run_argv_allowed, run_tool


def test_every_workflow_step_points_at_a_catalog_tool():
    known = {tool.id for tool in TOOLS}
    for workflow in WORKFLOWS:
        assert workflow.steps
        for step in workflow.steps:
            assert step.tool in known, f"{workflow.id}/{step.id} -> {step.tool}"


def test_every_tool_module_is_whitelisted_and_importable():
    import importlib

    assert ALLOWED_MODULES == {tool.module for tool in TOOLS}
    for tool in TOOLS:
        module = importlib.import_module(tool.module)
        assert hasattr(module, "main")


def test_scan_command_uses_uv_frozen_module_path():
    argv = build_argv(get_tool("scan_servos"), {"max_id": 10, "port": "/dev/ttyAMA0"})
    assert argv[:6] == [
        "uv",
        "run",
        "--frozen",
        "python",
        "-m",
        "mio_core_services.firmware.setup.scan_servos",
    ]
    assert argv[argv.index("--max-id") + 1] == "10"


def test_zero_servos_puts_ids_positionally():
    line = command_line(get_tool("zero_servos"), {"ids": "1 2"})
    assert "python -m mio_core_services.firmware.calibration.zero_servos 1 2" in line
    assert "--keep-torque" not in line


def test_encode_requires_new_id():
    with pytest.raises(ValueError, match="new_id"):
        build_argv(get_tool("encode_servo_id"), {})


def test_bool_flags_are_omitted_unless_set():
    argv = build_argv(get_tool("read_servo"), {"diagnose": True, "id": 2})
    assert "--diagnose" in argv
    assert argv[argv.index("--id") + 1] == "2"
    argv = build_argv(get_tool("read_servo"), {"diagnose": False})
    assert "--diagnose" not in argv


def test_zero_servos_workflow_builds_tty_command():
    workflow = get_workflow("zero-servos")
    argv = argv_for_step(workflow, "zero", {"ids": "1 2", "step": 2})
    assert argv[5] == "mio_core_services.firmware.calibration.zero_servos"
    assert argv[6:8] == ["1", "2"]
    assert argv[argv.index("--step") + 1] == "2"


def test_step_values_copy_id_onto_repeatable_ids():
    workflow = get_workflow("calibrate-step-by-step")
    argv = argv_for_step(workflow, "rehearse", {"id": 2})
    assert "--id" in argv
    assert argv[argv.index("--id") + 1] == "2"
    assert argv[argv.index("--cycles") + 1] == "1"


def test_runner_skips_without_confirm_and_skips_tty():
    called = []

    def fake_run(*args, **kwargs):
        called.append(args[0])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    skipped = run_tool("scan_servos", {"max_id": 4}, confirm=False, runner=fake_run)
    assert skipped.skipped
    assert not called

    tty = run_tool("zero_servos", {"ids": "1 2"}, confirm=True, runner=fake_run)
    assert tty.skipped
    assert "TTY" in tty.skip_reason
    assert not called

    ran = run_tool("scan_servos", {"max_id": 4}, confirm=True, runner=fake_run)
    assert not ran.skipped
    assert ran.returncode == 0
    assert called[0][5] == "mio_core_services.firmware.setup.scan_servos"


def test_http_catalog_and_command_endpoints():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FirmwareLabHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/catalog")
        catalog = json.loads(conn.getresponse().read())
        assert catalog["workflows"][0]["id"] == "first-contact"
        assert any(tool["id"] == "zero_servos" for tool in catalog["tools"])

        conn.request("GET", "/")
        home = conn.getresponse()
        body = home.read().decode()
        assert home.status == 200
        assert "Firmware lab" in body

        payload = json.dumps(
            {
                "workflow_id": "zero-servos",
                "step_id": "zero",
                "values": {"ids": "1 2"},
            }
        ).encode()
        conn.request(
            "POST",
            "/api/command",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        command = json.loads(conn.getresponse().read())
        assert command["needs_tty"] is True
        assert "zero_servos 1 2" in command["command"]

        conn.request(
            "POST",
            "/api/run",
            body=json.dumps(
                {
                    "workflow_id": "zero-servos",
                    "step_id": "zero",
                    "confirm": True,
                    "values": {"ids": "1 2"},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        ran = json.loads(conn.getresponse().read())
        assert ran["skipped"] is True
        assert "TTY" in ran["skip_reason"]
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_modules_are_not_runnable():
    assert not run_argv_allowed(["uv", "run", "--frozen", "python", "-m", "os"])
    assert run_argv_allowed(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "-m",
            "mio_core_services.firmware.setup.scan_servos",
        ]
    )
