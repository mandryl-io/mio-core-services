import sys
from pathlib import Path

WAKEPHRASE_DIR = Path(__file__).resolve().parents[1] / "livekit-wakephrase"
if str(WAKEPHRASE_DIR) not in sys.path:
    sys.path.insert(0, str(WAKEPHRASE_DIR))

from config_paths import REMOTE_DATA_DIR, REMOTE_OUTPUT_DIR, rebase_path, remount_config


def test_rebase_relative_data_paths() -> None:
    assert rebase_path("./data/backgrounds", "./data", REMOTE_DATA_DIR) == str(
        REMOTE_DATA_DIR / "backgrounds"
    )
    assert rebase_path("./data", "./data", REMOTE_DATA_DIR) == str(REMOTE_DATA_DIR)


def test_rebase_leaves_absolute_paths() -> None:
    assert (
        rebase_path("/mnt/custom/noise", "./data", REMOTE_DATA_DIR)
        == "/mnt/custom/noise"
    )


def test_remount_hey_mio_style_config() -> None:
    remounted = remount_config(
        {
            "model_name": "hey_mio",
            "data_dir": "./data",
            "output_dir": "./output",
            "augmentation": {
                "background_paths": ["./data/backgrounds"],
                "rir_paths": ["./data/rirs"],
            },
        }
    )
    assert remounted["data_dir"] == str(REMOTE_DATA_DIR)
    assert remounted["output_dir"] == str(REMOTE_OUTPUT_DIR)
    assert remounted["augmentation"]["background_paths"] == [
        str(REMOTE_DATA_DIR / "backgrounds")
    ]
    assert remounted["augmentation"]["rir_paths"] == [str(REMOTE_DATA_DIR / "rirs")]


def test_checked_in_configs_use_relative_paths() -> None:
    for name in ("hey_mio.yaml", "hey_mio_test.yaml"):
        text = (WAKEPHRASE_DIR / "configs" / name).read_text()
        assert "data_dir: ./data" in text
        assert "output_dir: ./output" in text
        assert "background_paths: [./data/backgrounds]" in text
        assert "rir_paths: [./data/rirs]" in text


def test_modal_app_is_valid_python() -> None:
    import ast

    ast.parse((WAKEPHRASE_DIR / "modal_app.py").read_text())
