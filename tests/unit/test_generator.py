# tests/unit/test_generator.py
"""Unit tests for the Generation context."""

import json

import pytest

from customer_support.core.exceptions import GenerationError
from customer_support.generation.generator import ResponseGenerator
from customer_support.generation.models import GeneratorResult
from tests.conftest import EmptyLLMClient, FailingLLMClient, StubLLMClient

CATEGORY = "tracking"
CONTEXT_DOCS = [
    "Q: Where is my order?\nA: Log in and visit My Orders.",
    "Q: How long does shipping take?\nA: Standard shipping takes 3-5 days.",
]

_VALID_RESPONSE = json.dumps({
    "answer": "Your order is on its way. Visit My Orders for details. Thank you.",
    "sources_used": [1],
})


@pytest.fixture()
def generator() -> ResponseGenerator:
    return ResponseGenerator(client=StubLLMClient(content=_VALID_RESPONSE))


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

    def test_generate_result_sources_from_json(self) -> None:
        gen = ResponseGenerator(
            client=StubLLMClient(content=json.dumps({
                "answer": "Your order is on its way. Thank you.",
                "sources_used": [1, 2],
            }))
        )
        result = gen.generate("query", CATEGORY, CONTEXT_DOCS)
        assert result.sources == [1, 2]

    def test_generate_result_empty_sources_when_none_used(self) -> None:
        gen = ResponseGenerator(
            client=StubLLMClient(content=json.dumps({
                "answer": "I don't have that information. Thank you.",
                "sources_used": [],
            }))
        )
        result = gen.generate("query", CATEGORY, CONTEXT_DOCS)
        assert result.sources == []

    def test_generate_tracks_token_usage(self) -> None:
        gen = ResponseGenerator(
            client=StubLLMClient(content=_VALID_RESPONSE, tokens_used=42)
        )
        result = gen.generate("query", CATEGORY, CONTEXT_DOCS)
        assert result.tokens_used == 42

    def test_generate_works_with_empty_context(
        self, generator: ResponseGenerator
    ) -> None:
        result = generator.generate("where is my order?", CATEGORY, [])
        assert isinstance(result, GeneratorResult)


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

    def test_generate_raises_generation_error_on_malformed_json(self) -> None:
        gen = ResponseGenerator(client=StubLLMClient(content="not valid json {{"))
        with pytest.raises(GenerationError, match="not valid JSON"):
            gen.generate("query", CATEGORY, CONTEXT_DOCS)

    def test_generate_raises_generation_error_on_missing_answer_field(self) -> None:
        gen = ResponseGenerator(
            client=StubLLMClient(content=json.dumps({"sources_used": [1]}))
        )
        with pytest.raises(GenerationError, match="missing 'answer' field"):
            gen.generate("query", CATEGORY, CONTEXT_DOCS)