MIO_LOCAL_VEC_MEMORY_STORE = "mio-local-vec-memory-store"
DEFAULT_MIO_CHROMA_PATH = "./mio-chroma"

MIO_FACE_COLLECTION = "mio-face-embeddings"
DEFAULT_FACE_CHROMA_PATH = "./mio-faces"
DEFAULT_FACE_MATCH_THRESHOLD = 0.45

DEFAULT_EMBEDDING_MODEL = "thenlper/gte-small"
DEFAULT_EMBEDDING_DIMENSIONS = 384

DEFAULT_STT_MODEL = "gpt-4o-transcribe"
DEFAULT_CONVERSATION_LLM_MODEL = "claude-opus-5"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "marin"
DEFAULT_TTS_INSTRUCTIONS = (
    "Speak warmly, gently, and naturally, like a patient friend. "
    "Use an unhurried conversational pace."
)
DEFAULT_BOT_NAME = "Mio"
DEFAULT_INITIAL_MESSAGE = (
    f"Hi, I'm {DEFAULT_BOT_NAME}. It's good to sit down with you. "
    "If something's already on your mind we can start there — "
    "otherwise I'll get us going."
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

