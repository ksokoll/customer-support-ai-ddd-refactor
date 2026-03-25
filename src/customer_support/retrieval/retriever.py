# retrieval/retriever.py
"""Retrieval context: Protocol definition and concrete implementations.

FAISSRetriever: local development and tests (reads JSONL from disk).
BlobRetriever: production (reads JSONL from Azure Blob Storage).

Both receive EmbeddingClient via constructor injection. Both must use
the same EmbeddingClient implementation and model name as store_builder.py.
Using different models at build time vs. retrieval time causes silent
embedding skew: queries and documents occupy different vector spaces
and similarity scores become meaningless.

Index layout on disk:
  <vector_db_path>/index.faiss   -- FAISS IndexFlatL2
  <vector_db_path>/texts.json    -- parallel list[str] mapping index
                                    position to original document text
"""

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import faiss
import numpy as np

from customer_support.core.config import settings
from customer_support.core.exceptions import RetrievalError
from customer_support.services.client import EmbeddingClient

logger = logging.getLogger(__name__)

_INDEX_FILENAME = "index.faiss"
_TEXTS_FILENAME = "texts.json"


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class RetrieverProtocol(Protocol):
    """Minimal interface every retriever implementation must satisfy."""

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return the top-k most relevant documents for a query.

        Args:
            query: Raw query string from the customer.
            k: Number of documents to return.

        Returns:
            List of document strings, ordered by descending relevance.
            May be shorter than k if the index contains fewer documents.

        Raises:
            RetrievalError: If the retrieval operation fails.
        """
        ...


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_qa_line(line: str) -> str:
    """Parse a single JSONL line into a formatted Q&A string.

    Args:
        line: A single JSON line with "query" and "gold_answer" fields.

    Returns:
        Formatted string: "Q: ...\nA: ..."

    Raises:
        json.JSONDecodeError: If the line is not valid JSON.
        KeyError: If required fields are missing.
    """
    qa = json.loads(line)
    return f"Q: {qa['query']}\nA: {qa['gold_answer']}"


def _parse_jsonl(raw: str) -> list[str]:
    """Parse a multi-line JSONL string into a list of Q&A strings.

    Skips blank lines and logs a warning for malformed entries.

    Args:
        raw: Full JSONL content as a string.

    Returns:
        List of formatted Q&A strings.

    Raises:
        RetrievalError: If no valid entries are found.
    """
    texts: list[str] = []
    for lineno, line in enumerate(raw.strip().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            texts.append(_parse_qa_line(line))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping malformed JSONL line %d: %s", lineno, exc)

    if not texts:
        raise RetrievalError("Knowledge base contains no valid Q&A entries.")

    return texts


def _build_faiss_index(
    texts: list[str],
    client: EmbeddingClient,
) -> faiss.IndexFlatL2:
    """Embed texts and build a FAISS IndexFlatL2.

    Args:
        texts: List of document strings to embed and index.
        client: EmbeddingClient used to generate vectors.

    Returns:
        Populated FAISS index.

    Raises:
        RetrievalError: If embedding fails.
    """
    try:
        vectors = client.embed(texts)
    except Exception as exc:
        raise RetrievalError(f"Failed to embed documents: {exc}") from exc

    matrix = np.array(vectors, dtype=np.float32)
    index = faiss.IndexFlatL2(matrix.shape[1])
    index.add(matrix)
    return index


def _load_index(vector_db_path: str) -> tuple[faiss.IndexFlatL2, list[str]]:
    """Load FAISS index and parallel text list from disk.

    Args:
        vector_db_path: Directory containing index.faiss and texts.json.

    Returns:
        Tuple of (faiss index, list of document strings).

    Raises:
        RetrievalError: If index files are missing or cannot be loaded.
    """
    db_path = Path(vector_db_path)
    index_path = db_path / _INDEX_FILENAME
    texts_path = db_path / _TEXTS_FILENAME

    if not index_path.exists() or not texts_path.exists():
        raise RetrievalError(
            f"Vector store not found at '{vector_db_path}'. "
            "Run 'make build-store' to build the index."
        )

    try:
        index = faiss.read_index(str(index_path))
        with open(texts_path, encoding="utf-8") as fh:
            texts: list[str] = json.load(fh)
    except (RuntimeError, json.JSONDecodeError, OSError) as exc:
        raise RetrievalError(f"Failed to load vector store: {exc}") from exc

    logger.info("Loaded FAISS index with %d documents", index.ntotal)
    return index, texts


def _search(
    index: faiss.IndexFlatL2,
    texts: list[str],
    query_vector: list[float],
    k: int,
) -> list[str]:
    """Run FAISS similarity search and map results back to text.

    Args:
        index: Loaded FAISS index.
        texts: Parallel text list aligned with index positions.
        query_vector: Embedding of the query string.
        k: Number of results to return.

    Returns:
        List of document strings ordered by ascending L2 distance.
    """
    query_np = np.array([query_vector], dtype=np.float32)
    effective_k = min(k, index.ntotal)
    _, indices = index.search(query_np, effective_k)
    return [texts[i] for i in indices[0] if i >= 0]


# ── FAISSRetriever ────────────────────────────────────────────────────────────

class FAISSRetriever:
    """Local retriever reading a pre-built FAISS index from disk.

    Used in local development and unit/integration tests.
    Requires the index to be built first via store_builder.py.
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_db_path: str | None = None,
    ) -> None:
        """Initialise FAISSRetriever.

        Args:
            embedding_client: Client used to embed queries at retrieval time.
                Must be the same implementation used during store_builder.py.
            vector_db_path: Path to directory containing index files.
                Defaults to settings.vector_db_path.
        """
        self._client = embedding_client
        self._db_path = vector_db_path or settings.vector_db_path
        self._index, self._texts = _load_index(self._db_path)

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        """Return top-k relevant documents for a query.

        Args:
            query: Raw query string from the customer.
            k: Number of documents to return.

        Returns:
            List of document strings ordered by relevance.

        Raises:
            RetrievalError: If embedding or search fails.
        """
        try:
            query_vector = self._client.embed([query])[0]
        except Exception as exc:
            raise RetrievalError(f"Failed to embed query: {exc}") from exc

        return _search(self._index, self._texts, query_vector, k)


# ── BlobRetriever ─────────────────────────────────────────────────────────────

class BlobRetriever:
    """Production retriever loading JSONL from Azure Blob Storage.

    Builds a transient in-memory FAISS index on startup.
    No index files are written to disk.
    """

    def __init__(self, embedding_client: EmbeddingClient) -> None:
        """Initialise BlobRetriever.

        Validates Azure configuration upfront so the retriever fails fast
        on startup rather than on the first retrieve() call.

        Args:
            embedding_client: Client used to embed documents and queries.

        Raises:
            RetrievalError: If azure-storage-blob is not installed or
                required config values are missing.
        """
        try:
            from azure.storage.blob import BlobServiceClient as _BlobServiceClient  # noqa: PLC0415
            self._BlobServiceClient = _BlobServiceClient
        except ImportError as exc:
            raise RetrievalError(
                "azure-storage-blob is not installed. "
                "Run: pip install -e '.[azure]'"
            ) from exc

        if not settings.blob_connection_string or not settings.blob_container_name:
            raise RetrievalError(
                "BLOB_CONNECTION_STRING and BLOB_CONTAINER_NAME must be set "
                "when ENABLE_BLOB_RETRIEVAL=true."
            )

        self._client = embedding_client
        self._index, self._texts = self._build_from_blob()

    def _build_from_blob(self) -> tuple[faiss.IndexFlatL2, list[str]]:
        """Orchestrate download, parse, and index build.

        Returns:
            Tuple of (faiss index, list of document strings).
        """
        raw = self._download_blob()
        texts = _parse_jsonl(raw)
        index = _build_faiss_index(texts, self._client)
        logger.info("Built in-memory FAISS index with %d documents from blob", len(texts))
        return index, texts

    def _download_blob(self) -> str:
        """Download the knowledge base JSONL from Azure Blob Storage.

        Returns:
            Raw JSONL content as a string.

        Raises:
            RetrievalError: If the download fails.
        """
        try:
            from azure.core.exceptions import AzureError  # noqa: PLC0415
        except ImportError as exc:
            raise RetrievalError("azure-core is not installed.") from exc

        try:
            blob_service = self._BlobServiceClient.from_connection_string(
                settings.blob_connection_string
            )
            blob_client = blob_service.get_blob_client(
                container=settings.blob_container_name,
                blob=settings.knowledge_blob_name,
            )
            return blob_client.download_blob().readall().decode("utf-8")
        except AzureError as exc:
            raise RetrievalError(
                f"Failed to download knowledge base blob: {exc}"
            ) from exc

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        """Return top-k relevant documents for a query.

        Args:
            query: Raw query string from the customer.
            k: Number of documents to return.

        Returns:
            List of document strings ordered by relevance.

        Raises:
            RetrievalError: If embedding or search fails.
        """
        try:
            query_vector = self._client.embed([query])[0]
        except Exception as exc:
            raise RetrievalError(f"Failed to embed query: {exc}") from exc

        return _search(self._index, self._texts, query_vector, k)