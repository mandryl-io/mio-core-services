from mio_core_services.memory.mem0 import Mem0TurnMemory, inject_mem0_turn

__all__ = [
    "Document",
    "Mem0TurnMemory",
    "MioTextEmbedder",
    "SentenceTransformerEmbedder",
    "MioVectorStore",
    "SearchResult",
    "inject_mem0_turn",
]


def __getattr__(name: str):
    if name in {"Document", "MioVectorStore", "SearchResult"}:
        from mio_core_services.memory.store import (
            Document,
            MioVectorStore,
            SearchResult,
        )

        return {
            "Document": Document,
            "MioVectorStore": MioVectorStore,
            "SearchResult": SearchResult,
        }[name]
    if name in {"MioTextEmbedder", "SentenceTransformerEmbedder"}:
        from mio_core_services.memory.embeddings import (
            MioTextEmbedder,
            SentenceTransformerEmbedder,
        )

        return {
            "MioTextEmbedder": MioTextEmbedder,
            "SentenceTransformerEmbedder": SentenceTransformerEmbedder,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
