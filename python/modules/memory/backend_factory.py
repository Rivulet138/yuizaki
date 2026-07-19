from __future__ import annotations

import logging

from ..core.config import MemoryConfig

from .backend import MemoryBackend
from .indexed_backend import IndexedMemoryBackend
from .vector_client import QdrantVectorStore
from .vector_store import LazyEmbeddingService, VectorStore
from .sqlite_store import SQLiteMemoryStore

logger = logging.getLogger(__name__)


def create_memory_backend(config: MemoryConfig) -> MemoryBackend:
    embedding_service = LazyEmbeddingService(model_name=config.embedding_model)
    backend = (config.backend or "inmemory").strip().lower()

    if backend == "qdrant":
        if not config.qdrant_url.strip():
            raise ValueError("qdrant_url_required")
        logger.info("Using SQLite memory authority with Qdrant index: %s", config.qdrant_url)
        authority = SQLiteMemoryStore(
            db_path=config.sqlite_path,
            embedding_service=embedding_service,
        )
        index = QdrantVectorStore(
            qdrant_url=config.qdrant_url,
            qdrant_api_key=config.qdrant_api_key,
            collection_name=config.qdrant_collection,
            timeout=config.qdrant_timeout,
            embedding_service=embedding_service,
        )
        return IndexedMemoryBackend(authority=authority, index=index)

    if backend == "sqlite":
        logger.info("Using SQLite memory authority: %s", config.sqlite_path)
        return SQLiteMemoryStore(
            db_path=config.sqlite_path,
            embedding_service=embedding_service,
        )

    logger.info("Using in-memory vector backend")
    return VectorStore(embedding_service=embedding_service)
