# Pipecat evals

These YAML files drive the live Mio bot through [Pipecat evals](https://docs.pipecat.ai/pipecat/evals/overview). They are **not pytest**.

The current scenarios (`grief.yaml`, `pride.yaml`, `loneliness.yaml`) are **LLM-generated plumbing**. They exist to prove the harness connects, greets, and judges a turn. Do not treat them as a real companionship suite or keep them long-term.

## Prerequisites

```bash
uv sync
uv tool install "pipecat-ai[cli]"   # once, if `pipecat` is not on PATH
ollama pull gemma2:9b               # default judge
export OPENAI_API_KEY=...           # required; the bot is live Realtime
```

## Run

From the repo root, start the eval bot and run every scenario:

```bash
make eval
```

One file:

```bash
make eval EVAL_SCENARIOS=tests/scenarios/grief.yaml
```

Or two terminals. Terminal 1 — bot on the eval transport (default port 7860):

```bash
uv run main.py -t eval
```

Terminal 2 — one scenario:

```bash
pipecat eval run tests/scenarios/grief.yaml
```

All YAML in this directory:

```bash
pipecat eval run tests/scenarios/*.yaml
```

Useful flags:

```bash
pipecat eval run tests/scenarios/grief.yaml -v
pipecat eval run tests/scenarios/grief.yaml --bot-url ws://localhost:7860
```

`-v` prints each turn as it resolves. `--bot-url` is only needed if the bot is not on `ws://localhost:7860`.
