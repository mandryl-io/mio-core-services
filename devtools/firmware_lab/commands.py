"""Build argv lists for firmware CLIs from catalog flags and form values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from devtools.firmware_lab.catalog import (
    ZEROS_FILE,
    Flag,
    Step,
    Tool,
    Workflow,
    get_tool,
)
from mio_core_services.firmware.runtime.sts3215 import DEFAULT_BAUDRATE, DEFAULT_PORT

UV_PREFIX = ("uv", "run", "--frozen", "python", "-m")


def shared_defaults() -> dict[str, Any]:
    return {
        "port": DEFAULT_PORT,
        "baudrate": DEFAULT_BAUDRATE,
        "zeros": ZEROS_FILE,
        "zeros_positional": ZEROS_FILE,
    }


def _is_empty(value: Any) -> bool:
    return value is None or value is False or value == ""


def _split_multi(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).replace(",", " ")
    return [token for token in text.split() if token]


def _coerce(flag: Flag, value: Any) -> Any:
    if _is_empty(value) and flag.kind != "bool":
        return None
    if flag.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if flag.kind == "int":
        return int(value)
    if flag.kind == "float":
        return float(value)
    if flag.kind == "choice":
        text = str(value)
        if flag.choices and text not in flag.choices:
            raise ValueError(f"{flag.key} must be one of {', '.join(flag.choices)}")
        return text
    return str(value)


def build_argv(tool: Tool, values: Mapping[str, Any]) -> list[str]:
    """Return the uv-wrapped argv for one firmware module."""
    merged = {**shared_defaults(), **dict(values)}
    argv = [*UV_PREFIX, tool.module]
    missing: list[str] = []
    for flag in tool.flags:
        raw = merged.get(flag.key, flag.default)
        if flag.repeatable:
            parts = _split_multi(raw)
            if not parts:
                if flag.required:
                    missing.append(flag.key)
                continue
            for part in parts:
                argv.extend([flag.flag, part] if flag.flag else [part])
            continue
        if flag.flag is None:
            parts = _split_multi(raw if raw is not None else flag.default)
            if not parts:
                if flag.required:
                    missing.append(flag.key)
                continue
            argv.extend(parts)
            continue
        if _is_empty(raw):
            if flag.required:
                missing.append(flag.key)
            continue
        coerced = _coerce(flag, raw)
        if flag.kind == "bool":
            if coerced:
                argv.append(flag.flag)
            continue
        if coerced is None:
            if flag.required:
                missing.append(flag.key)
            continue
        argv.extend([flag.flag, str(coerced)])
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))
    return argv


def command_line(tool: Tool, values: Mapping[str, Any]) -> str:
    return " ".join(build_argv(tool, values))


def step_values(
    workflow: Workflow,
    step: Step,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Layer shared defaults, workflow params, step defaults, then the form."""
    merged = shared_defaults()
    merged.update(step.defaults)
    merged.update(dict(values))
    if merged.get("zeros") and not merged.get("zeros_positional"):
        merged["zeros_positional"] = merged["zeros"]
    if merged.get("id") not in (None, "") and not merged.get("ids"):
        merged["ids"] = merged["id"]
    return merged


def argv_for_step(
    workflow: Workflow,
    step_id: str,
    values: Mapping[str, Any],
) -> list[str]:
    for step in workflow.steps:
        if step.id == step_id:
            tool = get_tool(step.tool)
            return build_argv(tool, step_values(workflow, step, values))
    raise KeyError(f"Unknown step {step_id!r} in workflow {workflow.id}")
