# To Run

Ensure you have `uv`, run `uv sync` to install the dependencies.

Then, run `uv run main.py` to start the pipeline example.

# Tests

Unit tests:

```
uv run pytest
```

Scenarios live in `tests/scenarios/` and are run with [Pipecat evals](https://docs.pipecat.ai/pipecat/evals/overview), not pytest. Install the CLI once if you do not have it (`uv tool install "pipecat-ai[cli]"`).

Start the agent on the eval transport in one terminal:

```
uv run main.py -t eval
```

In another terminal, run every scenario:

```
pipecat eval run tests/scenarios/*.yaml
```

The default judge is Ollama (`gemma2:9b`). Pull it with `ollama pull gemma2:9b` if needed.
