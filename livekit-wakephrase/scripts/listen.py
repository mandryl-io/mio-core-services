#!/usr/bin/env python3
"""Listen on the default mic for the Hey Mio wakephrase."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models/hey_mio.onnx"),
        help="Path to the exported ONNX classifier",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Minimum score (0-1) to count as a detection",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Minimum seconds between consecutive detections",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.model.is_file():
        raise SystemExit(
            f"Model not found: {args.model}\n"
            "Train with `make train` or `make modal-train`, then `make copy-model`, "
            "or pass --model path/to/hey_mio.onnx"
        )

    from livekit.wakeword import WakeWordListener, WakeWordModel

    model = WakeWordModel(models=[str(args.model)])
    print(
        f"Listening for Hey Mio "
        f"(threshold={args.threshold}, debounce={args.debounce}s)…"
    )

    async with WakeWordListener(
        model,
        threshold=args.threshold,
        debounce=args.debounce,
    ) as listener:
        while True:
            detection = await listener.wait_for_detection()
            print(
                f"Detected {detection.name} "
                f"(confidence={detection.confidence:.2f})"
            )


if __name__ == "__main__":
    asyncio.run(main())
