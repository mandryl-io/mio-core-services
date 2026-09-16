.PHONY: run-conversation-service download-files

ALSA_CONFIG_DIR ?= /usr/share/alsa
ALSA_CONFIG_PATH ?= /usr/share/alsa/alsa.conf
MIO_AUDIO_INPUT ?= 1
MIO_AUDIO_OUTPUT ?= 0

run-conversation-service:
	ALSA_CONFIG_DIR=$(ALSA_CONFIG_DIR) ALSA_CONFIG_PATH=$(ALSA_CONFIG_PATH) \
	lk agent console --input-device $(MIO_AUDIO_INPUT) \
		--output-device $(MIO_AUDIO_OUTPUT) mio_core_services/conversation.py

download-files:
	uv run python -m livekit.agents download-files
