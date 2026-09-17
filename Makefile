.PHONY: run-conversation-service download-files

ALSA_CONFIG_DIR ?= /usr/share/alsa
ALSA_CONFIG_PATH ?= /usr/share/alsa/alsa.conf
MIO_AUDIO_INPUT ?= USB Audio Device
MIO_AUDIO_OUTPUT ?= UACDemoV1.0
MIO_SYSTEM_PROMPT_PATH ?= prompts/default.md
PA_ALSA_PLUGHW ?= 1

run-conversation-service:
	ALSA_CONFIG_DIR=$(ALSA_CONFIG_DIR) ALSA_CONFIG_PATH=$(ALSA_CONFIG_PATH) \
	PA_ALSA_PLUGHW=$(PA_ALSA_PLUGHW) \
	MIO_SYSTEM_PROMPT_PATH=$(MIO_SYSTEM_PROMPT_PATH) \
	lk agent console --input-device "$(MIO_AUDIO_INPUT)" \
		--output-device "$(MIO_AUDIO_OUTPUT)" mio_core_services/conversation.py

download-files:
	uv run python -m livekit.agents download-files
