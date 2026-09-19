.PHONY: run-conversation-service download-files setup-dev-osx

ALSA_CONFIG_DIR ?= /usr/share/alsa
ALSA_CONFIG_PATH ?= /usr/share/alsa/alsa.conf
# MIO_AUDIO_INPUT ?= USB PnP Sound Device
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

setup-dev-osx:
	@if [ "$$(uname -s)" != "Darwin" ]; then \
		echo "setup-dev-osx is for macOS."; \
		echo "On Linux, install the LiveKit CLI with:"; \
		echo "  sudo apt-get install -y jq"; \
		echo "  curl -sSL https://get.livekit.io/cli | bash"; \
		exit 1; \
	fi
	@command -v brew >/dev/null 2>&1 || { \
		echo "Homebrew is required. Install it from https://brew.sh"; \
		exit 1; \
	}
	@command -v uv >/dev/null 2>&1 || brew install uv
	brew install livekit-cli
	uv sync
	$(MAKE) download-files
