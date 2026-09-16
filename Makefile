.PHONY: run-conversation-service eval download-files

PIPECAT_HOST ?= localhost

EVAL_PORT ?= 7860
EVAL_BOT_URL ?= ws://$(PIPECAT_HOST):$(EVAL_PORT)
EVAL_SCENARIOS ?= tests/scenarios/*.yaml

run-conversation-service:
	uv run python -m mio_core_services.conversation console

download-files:
	uv run python -m mio_core_services.conversation download-files

eval:
	uv run main.py -t eval --port $(EVAL_PORT) & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null' EXIT INT TERM; \
	until nc -z $(PIPECAT_HOST) $(EVAL_PORT) 2>/dev/null; do sleep 0.5; done; \
	pipecat eval run $(EVAL_SCENARIOS) --bot-url $(EVAL_BOT_URL) -v
