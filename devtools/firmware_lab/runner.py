"""Run a whitelisted firmware CLI. TTY tools are refused."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devtools.firmware_lab.catalog import TOOLS, Tool, get_tool
from devtools.firmware_lab.commands import build_argv

ALLOWED_MODULES = frozenset(tool.module for tool in TOOLS)
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    skipped: bool = False
    skip_reason: str = ""


def run_tool(
    tool: Tool | str,
    values: Mapping[str, Any],
    *,
    confirm: bool,
    cwd: Path | None = None,
    timeout: float = 120.0,
    runner: Callable[..., Any] | None = None,
) -> RunResult:
    resolved = get_tool(tool) if isinstance(tool, str) else tool
    if resolved.module not in ALLOWED_MODULES:
        raise ValueError(f"Module is not in the firmware catalog: {resolved.module}")
    argv = build_argv(resolved, values)
    if not confirm:
        return RunResult(argv, -1, "", "", skipped=True, skip_reason="confirm is required")
    if resolved.needs_tty:
        return RunResult(
            argv,
            -1,
            "",
            "",
            skipped=True,
            skip_reason="This tool reads a keyboard TTY. Run the command in a real terminal (ssh -t).",
        )
    execute = runner or subprocess.run
    completed = execute(
        argv,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return RunResult(
        argv=list(argv) if not isinstance(argv, list) else argv,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def run_argv_allowed(argv: Sequence[str]) -> bool:
    if len(argv) < 6:
        return False
    return tuple(argv[:5]) == ("uv", "run", "--frozen", "python", "-m") and argv[5] in ALLOWED_MODULES
