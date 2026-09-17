MIO_LOCAL_VEC_MEMORY_STORE = "mio-local-vec-memory-store"
DEFAULT_MIO_CHROMA_PATH = "./mio-chroma"

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
DEFAULT_INITIAL_MESSAGE = (
    f"Hi, I'm {DEFAULT_BOT_NAME}. It's good to sit down with you. "
    "If something's already on your mind we can start there — "
    "otherwise I'll get us going."
)
