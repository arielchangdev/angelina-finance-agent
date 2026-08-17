"""
RAG Engine for Angelina AI Financial Expert Agent.

Handles embedding, vector storage (ChromaDB), and semantic search using
sentence-transformers/all-MiniLM-L6-v2 locally.  All CPU-bound operations
(embedding + ChromaDB I/O) are offloaded to a thread pool via
asyncio.to_thread so the async interface never blocks the event loop.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import asyncio
import glob
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from app.models import Chunk

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy-initialised singletons
# ---------------------------------------------------------------------------

_sentence_transformer_model = None  # SentenceTransformer instance
_chroma_client = None               # chromadb.PersistentClient instance
_chroma_collection = None           # chromadb Collection instance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "angelina_knowledge"
VECTOR_STORE_PATH = "data/vector_store"
NOTEBOOKLM_DATA_PATH = "data/notebooklm"
SIMILARITY_THRESHOLD = 0.5
DEFAULT_TOP_K = 5
CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
TIKTOKEN_ENCODING = "cl100k_base"


# ---------------------------------------------------------------------------
# Internal synchronous helpers (executed in a thread pool)
# ---------------------------------------------------------------------------


def _load_embedding_model():
    """Load the SentenceTransformer model (blocking, called once at startup)."""
    global _sentence_transformer_model
    if _sentence_transformer_model is None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        log.info("Loading embedding model", model=EMBED_MODEL_NAME)
        _sentence_transformer_model = SentenceTransformer(EMBED_MODEL_NAME)
        log.info("Embedding model loaded")
    return _sentence_transformer_model


def _get_or_create_collection(persist_path: str):
    """Open or create the ChromaDB persistent client and collection."""
    global _chroma_client, _chroma_collection

    if _chroma_client is None or _chroma_collection is None:
        import chromadb  # type: ignore

        abs_path = str(Path(persist_path).resolve())
        os.makedirs(abs_path, exist_ok=True)
        log.info("Initialising ChromaDB", path=abs_path)
        _chroma_client = chromadb.PersistentClient(path=abs_path)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "ChromaDB collection ready",
            collection=COLLECTION_NAME,
            count=_chroma_collection.count(),
        )

    return _chroma_client, _chroma_collection


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using the loaded SentenceTransformer; returns list of float vectors."""
    model = _load_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return [emb.tolist() for emb in embeddings]


def _sync_search(query: str, top_k: int, persist_path: str) -> list[dict]:
    """
    Synchronous search: embed query, query ChromaDB, return result dicts.

    Each dict has: id, text, source_type, created_at, similarity.
    Filters out results with similarity < SIMILARITY_THRESHOLD.
    """
    _, collection = _get_or_create_collection(persist_path)

    if collection.count() == 0:
        return []

    query_embedding = _embed_texts([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    output: list[dict] = []
    if not results or not results.get("ids"):
        return output

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for chunk_id, text, meta, distance in zip(ids, documents, metadatas, distances):
        # ChromaDB cosine space: distance = 1 - similarity
        similarity = 1.0 - float(distance)
        if similarity >= SIMILARITY_THRESHOLD:
            output.append({
                "id": chunk_id,
                "text": text,
                "source_type": meta.get("source_type", "notebooklm"),
                "created_at": meta.get("created_at", ""),
                "similarity": similarity,
            })

    return output


def _sync_add_chunks(chunks_data: list[dict], persist_path: str) -> None:
    """
    Synchronous upsert: embed chunk texts and insert/update in ChromaDB.

    chunks_data items must have: id, text, source_type, created_at.
    """
    _, collection = _get_or_create_collection(persist_path)

    if not chunks_data:
        return

    texts = [c["text"] for c in chunks_data]
    embeddings = _embed_texts(texts)

    collection.upsert(
        ids=[c["id"] for c in chunks_data],
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {"source_type": c["source_type"], "created_at": c["created_at"]}
            for c in chunks_data
        ],
    )
    log.info("Chunks upserted", count=len(chunks_data))


def _sync_rebuild_index(export_path: str, persist_path: str) -> None:
    """
    Synchronous index rebuild.

    Steps:
      1. Delete and recreate the ChromaDB collection.
      2. Read the export file.
      3. Split with RecursiveCharacterTextSplitter (500-token chunks, 50-token overlap).
      4. Embed all chunks and insert them into the fresh collection.
    """
    global _chroma_client, _chroma_collection

    import chromadb  # type: ignore
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
    import tiktoken  # type: ignore

    abs_store = str(Path(persist_path).resolve())
    os.makedirs(abs_store, exist_ok=True)

    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=abs_store)

    # Delete existing collection (ignore if not found)
    try:
        _chroma_client.delete_collection(COLLECTION_NAME)
        log.info("Deleted existing collection", collection=COLLECTION_NAME)
    except Exception:
        pass

    _chroma_collection = _chroma_client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # Read export file
    export_text = Path(export_path).read_text(encoding="utf-8")
    log.info("Export file read", path=export_path, chars=len(export_text))

    # Build a tiktoken-based length function
    enc = tiktoken.get_encoding(TIKTOKEN_ENCODING)

    def _token_length(text: str) -> int:
        return len(enc.encode(text))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE_TOKENS,
        chunk_overlap=CHUNK_OVERLAP_TOKENS,
        length_function=_token_length,
        separators=["\n\n", "\n", "\u3002", ".", " ", ""],
    )

    raw_chunks = splitter.split_text(export_text)
    log.info("Text split into chunks", count=len(raw_chunks))

    if not raw_chunks:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    chunks_data = [
        {
            "id": str(uuid.uuid4()),
            "text": text,
            "source_type": "notebooklm",
            "created_at": now_iso,
        }
        for text in raw_chunks
    ]

    texts = [c["text"] for c in chunks_data]
    embeddings = _embed_texts(texts)

    _chroma_collection.upsert(
        ids=[c["id"] for c in chunks_data],
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {"source_type": c["source_type"], "created_at": c["created_at"]}
            for c in chunks_data
        ],
    )
    log.info("Index rebuilt", chunk_count=len(chunks_data))


def _find_latest_export(notebooklm_path: str) -> Optional[str]:
    """Return the most recently modified .txt or .md file under notebooklm_path."""
    patterns = [
        os.path.join(notebooklm_path, "**", "*.txt"),
        os.path.join(notebooklm_path, "**", "*.md"),
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern, recursive=True))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _sync_is_ready(persist_path: str) -> bool:
    """Disk-level readiness check -- used before in-process singletons are set."""
    try:
        import chromadb  # type: ignore

        abs_path = str(Path(persist_path).resolve())
        client = chromadb.PersistentClient(path=abs_path)
        collection_names = [c.name for c in client.list_collections()]
        return COLLECTION_NAME in collection_names
    except Exception as exc:
        log.warning("ChromaDB readiness check failed", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Public async RAGEngine class
# ---------------------------------------------------------------------------


class RAGEngine:
    """
    Async RAG Engine backed by ChromaDB and sentence-transformers.

    All public methods are async and offload blocking work to a thread pool
    via asyncio.to_thread so the event loop is never stalled.
    """

    def __init__(
        self,
        persist_path: str = VECTOR_STORE_PATH,
        notebooklm_path: str = NOTEBOOKLM_DATA_PATH,
    ) -> None:
        self._persist_path = persist_path
        self._notebooklm_path = notebooklm_path

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """
        Startup routine:
          - Load embedding model.
          - Open or create the ChromaDB collection.
          - On failure (missing/corrupt store), auto-rebuild from the last export.
        """
        try:
            await asyncio.to_thread(_load_embedding_model)
            await asyncio.to_thread(_get_or_create_collection, self._persist_path)
        except Exception as exc:
            log.error(
                "ChromaDB startup failed -- attempting auto-rebuild",
                error=str(exc),
            )
            await self._auto_rebuild()

    async def _auto_rebuild(self) -> None:
        """
        Auto-rebuild from the latest NotebookLM export when the persisted store
        is missing or unreadable (Requirement 4.7).
        """
        export_path = await asyncio.to_thread(
            _find_latest_export, self._notebooklm_path
        )
        if export_path is None:
            log.warning(
                "No NotebookLM export found; starting with an empty knowledge base",
                path=self._notebooklm_path,
            )
            # Ensure an empty (but functional) collection exists
            try:
                await asyncio.to_thread(_get_or_create_collection, self._persist_path)
            except Exception:
                pass
            return

        log.info("Auto-rebuilding index from export", export=export_path)
        await self.rebuild_index(export_path)

    # ------------------------------------------------------------------
    # Public interface (Requirement 4.2, 4.3, 4.4, 4.1, 4.5, 4.6)
    # ------------------------------------------------------------------

    async def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> "list[Chunk]":
        """
        Semantically search the knowledge base for the top-k most relevant chunks.

        Only chunks with cosine similarity >= 0.5 are returned.
        Returns an empty list if no chunk meets the threshold (Req 4.4).
        Results are sorted by descending similarity.
        """
        from app.models import Chunk  # avoid circular imports at module level

        raw: list[dict] = await asyncio.to_thread(
            _sync_search, query, top_k, self._persist_path
        )

        chunks = [
            Chunk(
                id=r["id"],
                text=r["text"],
                source_type=r["source_type"],
                created_at=r["created_at"],
                similarity=r["similarity"],
            )
            for r in raw
        ]
        chunks.sort(key=lambda c: c.similarity, reverse=True)
        return chunks

    async def add_chunks(self, chunks: "list[Chunk]") -> None:
        """
        Embed and upsert a list of Chunk objects into the knowledge base.

        Uses upsert semantics: existing chunks with the same id are updated.
        """
        if not chunks:
            return

        chunks_data = [
            {
                "id": c.id,
                "text": c.text,
                "source_type": c.source_type,
                "created_at": c.created_at,
            }
            for c in chunks
        ]
        await asyncio.to_thread(_sync_add_chunks, chunks_data, self._persist_path)

    async def rebuild_index(self, export_path: str) -> None:
        """
        Clear the ChromaDB collection and rebuild it from an export file.

        The export file is split with RecursiveCharacterTextSplitter using
        500-token chunks and 50-token overlap (tiktoken cl100k_base encoding).
        All chunks are embedded and inserted into the fresh collection.
        (Requirements 4.1, 4.5)
        """
        log.info("Rebuilding RAG index", export_path=export_path)
        await asyncio.to_thread(
            _sync_rebuild_index, export_path, self._persist_path
        )
        log.info("RAG index rebuild complete")

    def is_ready(self) -> bool:
        """
        Return True if the ChromaDB collection exists and is loadable.

        Fast path: in-process singleton is already set (after initialise()).
        Slow path: disk probe for health-checks before initialise() completes.
        (Requirement 4.6)
        """
        if _chroma_collection is not None:
            return True
        return _sync_is_ready(self._persist_path)

    async def get_collection_count(self) -> int:
        """Return the number of vectors currently stored in the collection."""

        def _count() -> int:
            _, collection = _get_or_create_collection(self._persist_path)
            return collection.count()

        return await asyncio.to_thread(_count)

    def reset_singletons(self) -> None:
        """
        Reset module-level singletons (for use in tests only).
        Allows tests to re-initialise ChromaDB against a temporary path.
        """
        global _sentence_transformer_model, _chroma_client, _chroma_collection
        _sentence_transformer_model = None
        _chroma_client = None
        _chroma_collection = None
