"""Train the Hey Mio wakephrase classifier on Modal Labs GPUs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import modal
from config_paths import (
    REMOTE_DATA_DIR,
    REMOTE_OUTPUT_DIR,
    VOLUME_MOUNT,
    remount_config,
)

APP_NAME = "mio-wakephrase"
VOLUME_NAME = "mio-wakephrase"
CONFIGS_REMOTE = Path("/root/configs")
HERE = Path(__file__).resolve().parent

volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("espeak-ng", "espeak-ng-data", "libsndfile1", "ffmpeg", "sox")
    .uv_pip_install(
        "livekit-wakeword[train,eval,export]>=0.2",
        "hf_transfer",
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",
            "HF_HOME": str(VOLUME_MOUNT / "hf-cache"),
        }
    )
    .add_local_dir(str(HERE / "configs"), remote_path=str(CONFIGS_REMOTE))
    .add_local_python_source("config_paths")
)

app = modal.App(APP_NAME, image=image)


def _hf_secret() -> modal.Secret:
    keys = [
        key for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN") if os.environ.get(key)
    ]
    if keys:
        return modal.Secret.from_local_environ(keys)
    return modal.Secret.from_dict({})


def _wakeword(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "livekit.wakeword", *args],
        check=True,
    )


def _prepare_config(config_name: str) -> Path:
    import yaml

    source = CONFIGS_REMOTE / Path(config_name).name
    if not source.is_file():
        raise FileNotFoundError(
            f"Config not found: {source}. Put YAML files in livekit-wakephrase/configs/"
        )
    remounted = remount_config(yaml.safe_load(source.read_text()))
    REMOTE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    REMOTE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (VOLUME_MOUNT / "hf-cache").mkdir(parents=True, exist_ok=True)
    dest = REMOTE_OUTPUT_DIR / "_active_config.yaml"
    dest.write_text(yaml.safe_dump(remounted, sort_keys=False))
    return dest


def _model_name(config_path: Path) -> str:
    import yaml

    data = yaml.safe_load(config_path.read_text())
    return str(data["model_name"])


def _artifact_paths(model_name: str) -> list[Path]:
    model_dir = REMOTE_OUTPUT_DIR / model_name
    names = (
        f"{model_name}.onnx",
        f"{model_name}.pt",
        f"{model_name}_metrics.json",
        f"{model_name}_det.png",
        f"{model_name}_eval.json",
    )
    return [model_dir / name for name in names]


def _commit() -> None:
    volume.commit()


_function_kwargs = {
    "volumes": {str(VOLUME_MOUNT): volume},
    "secrets": [_hf_secret()],
    "cpu": 8,
    "memory": 65536,
    "timeout": 24 * 60 * 60,
}


@app.function(**{**_function_kwargs, "timeout": 3 * 60 * 60})
def setup_assets(config_name: str) -> str:
    """Download Piper, ACAV features, RIRs, and MUSAN onto the volume."""
    config_path = _prepare_config(config_name)
    _wakeword("setup", "--config", str(config_path))
    _commit()
    return str(REMOTE_DATA_DIR)


@app.function(gpu="L40S", **_function_kwargs)
def train_model(config_name: str) -> dict[str, str]:
    """Generate, augment, train, export, and eval on a GPU container."""
    import torch

    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    print(f"Training device: {device}")
    config_path = _prepare_config(config_name)
    _wakeword("run", str(config_path))
    _commit()
    model_name = _model_name(config_path)
    found = {
        path.name: str(path) for path in _artifact_paths(model_name) if path.is_file()
    }
    if f"{model_name}.onnx" not in found:
        raise FileNotFoundError(f"ONNX export missing for {model_name}")
    return {"model_name": model_name, **found}


def _volume_entries(prefix: str):
    return list(volume.listdir(prefix))


def download_artifacts(model_name: str) -> list[Path]:
    """Copy exported artifacts from the Modal Volume into local output/ and models/."""
    output_dir = HERE / "output" / model_name
    models_dir = HERE / "models"
    output_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for entry in _volume_entries(f"output/{model_name}"):
        remote_path = entry.path.lstrip("/")
        name = Path(remote_path).name
        if not name.endswith((".onnx", ".pt", ".json", ".png")):
            continue
        payload = b"".join(volume.read_file(remote_path))
        local_path = output_dir / name
        local_path.write_bytes(payload)
        downloaded.append(local_path)
        if name.endswith(".onnx"):
            copied = models_dir / name
            copied.write_bytes(payload)
            downloaded.append(copied)
        print(f"Downloaded {remote_path} -> {local_path}")
    if not downloaded:
        raise FileNotFoundError(
            f"No artifacts under volume '{VOLUME_NAME}:output/{model_name}'. "
            "Train first, or run `modal volume ls mio-wakephrase output/`."
        )
    return downloaded


@app.local_entrypoint()
def main(
    config: str = "hey_mio.yaml",
    stage: str = "run",
    gpu: str = "L40S",
    skip_setup: bool = False,
    download: bool = True,
) -> None:
    """Submit wakephrase training to Modal.

    Stages: setup, train, run (setup+train), download.
    """
    config_name = Path(config).name
    if stage not in {"setup", "train", "run", "download"}:
        raise SystemExit(f"Unknown stage {stage!r}; use setup, train, run, or download")

    model_name = config_name.removesuffix(".yaml")
    if stage == "download":
        download_artifacts(model_name)
        return

    if stage in {"setup", "train", "run"} and not skip_setup:
        print(
            f"Downloading training assets for {config_name} onto volume {VOLUME_NAME}…"
        )
        setup_assets.remote(config_name)

    if stage in {"train", "run"}:
        print(f"Training {config_name} on {gpu}…")
        result = train_model.with_options(gpu=gpu).remote(config_name)
        model_name = result["model_name"]
        print(f"Remote artifacts: {result}")

    if download and stage in {"train", "run"}:
        download_artifacts(model_name)
