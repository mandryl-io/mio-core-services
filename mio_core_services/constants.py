MIO_LOCAL_VEC_MEMORY_STORE = "mio-local-vec-memory-store"
DEFAULT_MIO_CHROMA_PATH = "./mio-chroma"
DEFAULT_MEMORY_USER_ID = "mio-local"

MIO_FACE_COLLECTION = "mio-face-embeddings"
DEFAULT_FACE_CHROMA_PATH = "./mio-faces"
DEFAULT_FACE_MATCH_THRESHOLD = 0.45

DEFAULT_EMBEDDING_MODEL = "thenlper/gte-small"
DEFAULT_EMBEDDING_DIMENSIONS = 384

DEFAULT_STT_MODEL = "nova-3"
DEFAULT_CONVERSATION_LLM_MODEL = "zai-org/GLM-5.3"
DEFAULT_CONVERSATION_LLM_REASONING_EFFORT = "low"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "marin"
DEFAULT_TTS_INSTRUCTIONS = (
    "Speak warmly, gently, and naturally, like a patient friend. "
    "Use an unhurried conversational pace."
)
DEFAULT_BOT_NAME = "Mio"
INITIAL_GREETING_INSTRUCTIONS = (
    "This is the first turn of a new conversation. Greet the person as "
    f"{DEFAULT_BOT_NAME} in one or two short, natural spoken sentences. "
    "Sound like a kind person sitting down with them, not a script or an "
    "announcement, and vary the wording each time. Then offer two or three "
    "specific things you could do together, in a flowing sentence rather "
    "than a list: hearing what is on their mind, a word game, a little "
    "trivia, or talking about family, music, or a favourite memory. Invite "
    "them to pick one or to start somewhere else."
)

WIFI_DEVICE = "wlan0"
WIFI_SETUP_PORT = 80
WIFI_HOTSPOT_SSID = "Mio-Setup"
WIFI_HOTSPOT_PASSWORD = "miosetup"
WIFI_HOTSPOT_CONNECTION = "mio-setup"
WIFI_HOTSPOT_GATEWAY = "10.42.0.1"
WIFI_CONNECT_WAIT = 20.0
WIFI_RETRY_SLEEP = 2.0
WIFI_HOTSPOT_RETRY = 3.0
WIFI_FADE_PERIOD = 3.0
WIFI_FADE_STEP = 0.02
WIFI_JOIN_WAIT = 15.0
WIFI_JOIN_POLL = 1.0
WIFI_SETUP_POLL = 0.4
WIFI_FADE_JOIN_TIMEOUT = 1.0
