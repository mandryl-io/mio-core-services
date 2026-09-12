.PHONY: run-conversation-service eval setup run-kokoro

PIPECAT_HOST ?= localhost
PIPECAT_PORT ?= 8860
PIPECAT_BASE_URL ?= http://$(PIPECAT_HOST):$(PIPECAT_PORT)
CLIENT_PORT ?= 5173
MIO_BROWSER ?= firefox

EVAL_PORT ?= 7860
EVAL_BOT_URL ?= ws://$(PIPECAT_HOST):$(EVAL_PORT)
EVAL_SCENARIOS ?= tests/scenarios/*.yaml

setup:
	@command -v npm >/dev/null || { sudo apt-get update && sudo apt-get install -y nodejs npm; }

run-kokoro:
	uv run --with kokoro-onnx python -m mio_core_services.kokoro_server

run-conversation-service: setup
	PIPECAT_HEADLESS=1 uv run main.py --port $(PIPECAT_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until curl -sf $(PIPECAT_BASE_URL)/status >/dev/null; do sleep 0.5; done; \
	cd client && npm install && \
	MIO_BROWSER=$(MIO_BROWSER) PIPECAT_BASE_URL=$(PIPECAT_BASE_URL) CLIENT_PORT=$(CLIENT_PORT) npm start

eval:
	uv run main.py -t eval --port $(EVAL_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until nc -z $(PIPECAT_HOST) $(EVAL_PORT) 2>/dev/null; do sleep 0.5; done; \
	pipecat eval run $(EVAL_SCENARIOS) --bot-url $(EVAL_BOT_URL) -v
