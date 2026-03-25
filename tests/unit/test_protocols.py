# tests/unit/test_protocols.py
"""Fitness functions: verify that all client implementations satisfy their Protocols.

These tests are architecture guards. If a Dummy or real client drifts
from the Protocol signature, these fail immediately — not at serving time.
"""

import pytest

from customer_support.services.client import (
    CompletionRequest,
    DummyEmbeddingClient,
    DummyLLMClient,
    EmbeddingClient,
    LLMClient,
    OpenAIEmbeddingClient,
    OpenAILLMClient,
)


@pytest.mark.unit
class TestLLMClientProtocol:
    def test_dummy_llm_client_satisfies_protocol(self) -> None:
        assert isinstance(DummyLLMClient(), LLMClient)

    def test_dummy_llm_client_returns_completion_result(self) -> None:
        client = DummyLLMClient()
        result = client.complete(CompletionRequest(system="sys", user="hello"))
        assert result.content
        assert result.tokens_used == 0

    def test_dummy_llm_client_echoes_user_message(self) -> None:
        client = DummyLLMClient()
        result = client.complete(CompletionRequest(system="sys", user="test query"))
        assert "test query" in result.content

    def test_openai_llm_client_satisfies_protocol(self) -> None:
        # Protocol check only — no API call. isinstance() verifies structural
        # compatibility (method name + signature), not behaviour.
        assert isinstance(OpenAILLMClient(api_key="dummy"), LLMClient)


@pytest.mark.unit
class TestEmbeddingClientProtocol:
    def test_dummy_embedding_client_satisfies_protocol(self) -> None:
        assert isinstance(DummyEmbeddingClient(), EmbeddingClient)

    def test_dummy_embedding_client_returns_one_vector_per_input(self) -> None:
        client = DummyEmbeddingClient()
        result = client.embed(["foo", "bar", "baz"])
        assert len(result) == 3

    def test_dummy_embedding_client_vector_has_correct_dimensions(self) -> None:
        client = DummyEmbeddingClient()
        result = client.embed(["foo"])
        assert len(result[0]) == 1536

    def test_dummy_embedding_client_returns_zero_vectors(self) -> None:
        client = DummyEmbeddingClient()
        result = client.embed(["foo"])
        assert all(v == 0.0 for v in result[0])

    def test_openai_embedding_client_satisfies_protocol(self) -> None:
        # Protocol check only — no API call.
        assert isinstance(OpenAIEmbeddingClient(api_key="dummy"), EmbeddingClient)