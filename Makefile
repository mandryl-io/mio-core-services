.PHONY: run-conversation-service

PIPECAT_HOST ?= localhost
PIPECAT_PORT ?= 8860
PIPECAT_BASE_URL ?= http://$(PIPECAT_HOST):$(PIPECAT_PORT)
CLIENT_PORT ?= 5173

run-conversation-service:
	PIPECAT_HEADLESS=1 uv run main.py --port $(PIPECAT_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until curl -sf $(PIPECAT_BASE_URL)/status >/dev/null; do sleep 0.5; done; \
	cd client && npm install && \
	PIPECAT_BASE_URL=$(PIPECAT_BASE_URL) CLIENT_PORT=$(CLIENT_PORT) npm start
