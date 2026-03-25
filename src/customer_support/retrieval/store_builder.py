# retrieval/store_builder.py
"""One-time script: build a FAISS index from a JSONL knowledge base.

Run via: make build-store
         python -m customer_support.retrieval.store_builder

This script is NOT part of the serving path. The API Docker image does
not include it. It writes two files to vector_db_path:
  index.faiss   -- FAISS IndexFlatL2
  texts.json    -- parallel list[str] aligned with index positions

store_builder.py and retriever.py MUST use the same EmbeddingClient
implementation and the same model name. Different models produce
incompatible vector spaces and make similarity search meaningless.
"""

import json
import logging
import sys
from pathlib import Path

import faiss

from customer_support.core.config import settings
from customer_support.retrieval.retriever import (
    _INDEX_FILENAME,
    _TEXTS_FILENAME,
    _build_faiss_index,
    _parse_qa_line,
)
from customer_support.services.client import EmbeddingClient

logger = logging.getLogger(__name__)


class StoreBuilder:
    """Builds and persists a FAISS index from a JSONL knowledge base.

    Args:
        embedding_client: Client used to embed documents. Must match
            the client used by the retriever reading this index.
        knowledge_base_path: Path to JSONL file with Q&A pairs.
        vector_db_path: Output directory for index.faiss and texts.json.
    """

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        knowledge_base_path: str | None = None,
        vector_db_path: str | None = None,
    ) -> None:
        self._client = embedding_client
        self._kb_path = Path(knowledge_base_path or settings.knowledge_base_path)
        self._db_path = Path(vector_db_path or settings.vector_db_path)

    def build(self) -> None:
        """Load JSONL, embed all documents, build FAISS index, write to disk.

        Raises:
            FileNotFoundError: If the knowledge base JSONL does not exist.
            ValueError: If the knowledge base contains no valid entries.
            RuntimeError: If embedding or index construction fails.
        """
        texts = self._load_texts()
        logger.info("Loaded %d documents from %s", len(texts), self._kb_path)

        logger.info("Embedding %d documents...", len(texts))
        index = _build_faiss_index(texts, self._client)
        dimension = index.d

        self._db_path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(self._db_path / _INDEX_FILENAME))
        with open(self._db_path / _TEXTS_FILENAME, "w", encoding="utf-8") as fh:
            json.dump(texts, fh, ensure_ascii=False, indent=2)

        logger.info(
            "FAISS index written to %s (%d documents, %d dimensions)",
            self._db_path,
            len(texts),
            dimension,
        )

    def _load_texts(self) -> list[str]:
        """Parse JSONL and return formatted Q&A strings.

        Returns:
            List of strings in "Q: ...\nA: ..." format.

        Raises:
            FileNotFoundError: If the JSONL file does not exist.
            ValueError: If no valid entries are found.
        """
        if not self._kb_path.exists():
            raise FileNotFoundError(
                f"Knowledge base not found: {self._kb_path}"
            )

        texts: list[str] = []
        with open(self._kb_path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    texts.append(_parse_qa_line(line))
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Skipping line %d: %s", lineno, exc)

        if not texts:
            raise ValueError(
                f"No valid Q&A entries found in {self._kb_path}"
            )

        return texts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        from customer_support.services.client import OpenAIEmbeddingClient  # noqa: PLC0415
        embedding_client: EmbeddingClient = OpenAIEmbeddingClient()
    except ImportError:
        logger.error("openai package not installed. Run: pip install -e '.[openai]'")
        sys.exit(1)

    builder = StoreBuilder(embedding_client=embedding_client)
    builder.build()