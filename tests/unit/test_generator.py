# tests/unit/test_generator.py
"""Unit tests for the Generation context."""

import pytest

from customer_support.core.exceptions import GenerationError
from customer_support.generation.generator import ResponseGenerator
from customer_support.generation.models import GeneratorResult
from customer_support.services.client import CompletionRequest, CompletionResult

from tests.conftest import EmptyLLMClient, FailingLLMClient, StubLLMClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

CATEGORY = "tracking"
CONTEXT_DOCS = [
    "Q: Where is my order?\nA: Log in and visit My Orders.",
    "Q: How long does shipping take?\nA: Standard shipping takes 3-5 days.",
]


@pytest.fixture()
def generator() -> ResponseGenerator:
    return ResponseGenerator(
        client=StubLLMClient(
            content="Your order is on its way. Visit My Orders for details. [Source: 1] Thank you."
        )
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestResponseGeneratorReturnsResult:
    def test_generate_returns_generator_result(
        self, generator: ResponseGenerator
    ) -> None:
        result = generator.generate("where is my order?", CATEGORY, CONTEXT_DOCS)
        assert isinstance(result, GeneratorResult)

    def test_generate_result_has_non_empty_answer(
        self, generator: ResponseGenerator
    ) -> None:
        result = generator.generate("where is my order?", CATEGORY, CONTEXT_DOCS)
        assert result.answer

    def test_generate_tracks_token_usage(self) -> None:
        gen = ResponseGenerator(
            client=StubLLMClient("answer [Source: 1]", tokens_used=42)
        )
        result = gen.generate("query", CATEGORY, CONTEXT_DOCS)
        assert result.tokens_used == 42

    def test_generate_works_with_empty_context(
        self, generator: ResponseGenerator
    ) -> None:
        result = generator.generate("where is my order?", CATEGORY, [])
        assert isinstance(result, GeneratorResult)


@pytest.mark.unit
class TestExtractCitations:
    def test_extract_citations_finds_source_marker(self) -> None:
        result = ResponseGenerator._extract_citations("See [Source: 1] for details.")
        assert result == ["Source 1"]

    def test_extract_citations_finds_multiple_markers(self) -> None:
        result = ResponseGenerator._extract_citations("[Source: 1] and [Source: 2]")
        assert result == ["Source 1", "Source 2"]

    def test_extract_citations_deduplicates_repeated_markers(self) -> None:
        result = ResponseGenerator._extract_citations("[Source: 1] also [Source: 1]")
        assert result == ["Source 1"]

    def test_extract_citations_returns_empty_list_when_no_markers(self) -> None:
        result = ResponseGenerator._extract_citations("No citations here.")
        assert result == []

    def test_extract_citations_is_case_insensitive(self) -> None:
        result = ResponseGenerator._extract_citations("[source: 1]")
        assert result == ["Source 1"]


@pytest.mark.unit
class TestResponseGeneratorErrorHandling:
    def test_generate_raises_generation_error_on_empty_response(self) -> None:
        gen = ResponseGenerator(client=EmptyLLMClient())
        with pytest.raises(GenerationError, match="empty response"):
            gen.generate("query", CATEGORY, CONTEXT_DOCS)

    def test_generate_raises_generation_error_on_llm_failure(self) -> None:
        gen = ResponseGenerator(client=FailingLLMClient())
        with pytest.raises(GenerationError, match="LLM call failed"):
            gen.generate("query", CATEGORY, CONTEXT_DOCS)