.PHONY: run-conversation-service eval

PIPECAT_HOST ?= localhost
PIPECAT_PORT ?= 8860
PIPECAT_BASE_URL ?= http://$(PIPECAT_HOST):$(PIPECAT_PORT)
CLIENT_PORT ?= 5173

EVAL_PORT ?= 7860
EVAL_BOT_URL ?= ws://$(PIPECAT_HOST):$(EVAL_PORT)
EVAL_SCENARIOS ?= tests/scenarios/*.yaml

run-conversation-service:
	PIPECAT_HEADLESS=1 uv run main.py --port $(PIPECAT_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until curl -sf $(PIPECAT_BASE_URL)/status >/dev/null; do sleep 0.5; done; \
	cd client && npm install && \
	PIPECAT_BASE_URL=$(PIPECAT_BASE_URL) CLIENT_PORT=$(CLIENT_PORT) npm start

eval:
	uv run main.py -t eval --port $(EVAL_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until nc -z $(PIPECAT_HOST) $(EVAL_PORT) 2>/dev/null; do sleep 0.5; done; \
	pipecat eval run $(EVAL_SCENARIOS) --bot-url $(EVAL_BOT_URL) -v
