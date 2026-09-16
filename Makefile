.PHONY: run-conversation-service download-files

run-conversation-service:
	uv run python -m mio_core_services.conversation console

download-files:
	uv run python -m mio_core_services.conversation download-files
