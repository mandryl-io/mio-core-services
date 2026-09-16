# LiveKit wakephrase — "Hey Mio"

Train a custom [livekit-wakeword](https://github.com/livekit/livekit-wakeword)
classifier that detects the wake phrase **Hey Mio**. The pipeline synthesizes
training audio with TTS, augments it, trains a classifier head, and exports an
ONNX model you can load from Python, Rust, or Swift.

Upstream docs: [Wakeword detection](https://docs.livekit.io/agents/multimodality/audio/wakeword/).

## Layout

```
livekit-wakephrase/
  configs/
    hey_mio.yaml       # production-scale "Hey Mio" training
    hey_mio_test.yaml  # tiny end-to-end smoke run
  models/              # copy the exported .onnx here after training
  scripts/
    listen.py          # mic listener for a trained ONNX model
  Makefile
```

Generated `data/` and `output/` stay local (gitignored).

## Prerequisites

System packages (Ubuntu/Debian):

```bash
sudo apt install espeak-ng libsndfile1 ffmpeg sox portaudio19-dev
```

macOS:

```bash
brew install espeak-ng ffmpeg sox portaudio
```

Install the LiveKit wakeword CLI with training extras:

```bash
# with uv (recommended)
uv tool install "livekit-wakeword[train,eval,export]"

# or with pip
pip install "livekit-wakeword[train,eval,export]"
```

Python 3.11+ is required.

## Train "Hey Mio"

From this directory:

```bash
cd livekit-wakephrase

# 1) Download Piper TTS, embeddings, backgrounds, and RIRs
livekit-wakeword setup --config configs/hey_mio.yaml

# 2) Generate → augment → train → export ONNX
livekit-wakeword run configs/hey_mio.yaml

# 3) Optional: DET curve / AUT / FPPH on the validation set
livekit-wakeword eval configs/hey_mio.yaml
```

Or via Make:

```bash
make setup
make train
make eval
```

The exported classifier lands at:

```text
output/hey_mio/hey_mio.onnx
```

Copy it into `models/` for the listener script:

```bash
cp output/hey_mio/hey_mio.onnx models/
```

### Quick smoke test

Use the tiny config first to verify the toolchain (CPU-friendly, not production quality):

```bash
make setup-test
make train-test
```

## Inference

Install the runtime package (listener extra for microphone):

```bash
pip install "livekit-wakeword[listener]"
# or: uv add "livekit-wakeword[listener]"
```

```python
from livekit.wakeword import WakeWordModel

model = WakeWordModel(models=["models/hey_mio.onnx"])
scores = model.predict(audio_frame)  # 16 kHz int16 or float32
if scores["hey_mio"] > 0.5:
    print("Wake word detected!")
```

Mic loop:

```bash
python scripts/listen.py --model models/hey_mio.onnx --threshold 0.5
```

## Config notes

| Setting | `hey_mio.yaml` | Notes |
| --- | --- | --- |
| `target_phrases` | `hey mio`, `hey meo` | Pronunciation variants |
| `custom_negative_phrases` | mio / hey milo / hey meow / … | Reduce near-miss false positives |
| `model_type` | `conv_attention` | Best FPPH vs DNN |
| `model_size` | `medium` | Use `small` for tighter edge devices |
| `n_samples` | 25000 | Scale down for experiments |
| `steps` | 100000 | Production-scale; lower for prototypes |

Tune adversarial negatives after a first eval if common false triggers show up in-room.

## Stages (manual)

```bash
livekit-wakeword generate configs/hey_mio.yaml
livekit-wakeword augment configs/hey_mio.yaml
livekit-wakeword train configs/hey_mio.yaml
livekit-wakeword export configs/hey_mio.yaml
livekit-wakeword eval configs/hey_mio.yaml
```
