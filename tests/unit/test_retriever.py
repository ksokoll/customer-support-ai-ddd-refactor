# tests/unit/test_retriever.py
"""Unit tests for the Retrieval context.

All tests use synthetic data and DummyEmbeddingClient.
No real API calls, no real FAISS index on disk required
(except tests that explicitly build one in a tmp_path fixture).
"""

import json

import faiss
import numpy as np
import pytest

from customer_support.retrieval.retriever import (
    FAISSRetriever,
    RetrieverProtocol,
)
from customer_support.services.client import DummyEmbeddingClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

DUMMY_TEXTS = [
    "Q: How do I track my order?\nA: Log in and visit 'My Orders'.",
    "Q: What is the return policy?\nA: You have 30 days to return items.",
    "Q: How do I contact support?\nA: Email support@stylehub.com.",
]

DIMENSIONS = 1536  # matches DummyEmbeddingClient


def _build_test_index(tmp_path, texts: list[str]) -> str:
    """Build a minimal FAISS index in tmp_path and return the path."""
    vectors = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    index = faiss.IndexFlatL2(DIMENSIONS)
    index.add(vectors)
    faiss.write_index(index, str(tmp_path / "index.faiss"))
    with open(tmp_path / "texts.json", "w", encoding="utf-8") as fh:
        json.dump(texts, fh)
    return str(tmp_path)


@pytest.fixture()
def test_index(tmp_path):
    return _build_test_index(tmp_path, DUMMY_TEXTS)


@pytest.fixture()
def retriever(test_index):
    return FAISSRetriever(
        embedding_client=DummyEmbeddingClient(),
        vector_db_path=test_index,
    )


# ── Protocol fitness ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRetrieverProtocol:
    def test_faiss_retriever_satisfies_protocol(self, retriever: FAISSRetriever) -> None:
        assert isinstance(retriever, RetrieverProtocol)


# ── FAISSRetriever behaviour ──────────────────────────────────────────────────

@pytest.mark.unit
class TestFAISSRetriever:
    def test_retrieve_returns_list_of_strings(self, retriever: FAISSRetriever) -> None:
        results = retriever.retrieve("track my order", k=2)
        assert isinstance(results, list)
        assert all(isinstance(r, str) for r in results)

    def test_retrieve_respects_k_limit(self, retriever: FAISSRetriever) -> None:
        results = retriever.retrieve("return", k=2)
        assert len(results) <= 2

    def test_retrieve_returns_all_when_k_exceeds_index_size(
        self, retriever: FAISSRetriever
    ) -> None:
        results = retriever.retrieve("anything", k=100)
        assert len(results) == len(DUMMY_TEXTS)

    def test_retrieve_raises_retrieval_error_when_index_missing(
        self, tmp_path
    ) -> None:
        from customer_support.core.exceptions import RetrievalError

        with pytest.raises(RetrievalError, match="Vector store not found"):
            FAISSRetriever(
                embedding_client=DummyEmbeddingClient(),
                vector_db_path=str(tmp_path / "nonexistent"),
            )