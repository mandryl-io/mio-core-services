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
DEFAULT_INITIAL_MESSAGE = f"Hi, I'm {DEFAULT_BOT_NAME}. How are you today?"

