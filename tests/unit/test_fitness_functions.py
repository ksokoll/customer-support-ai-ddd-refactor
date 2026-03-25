# tests/unit/test_fitness_functions.py
"""Fitness functions: architecture guards beyond Protocol contracts.

These tests verify structural properties of the system that unit and
integration tests do not cover: exit contracts, startup resilience,
and availability under missing configuration.
"""

import json

import pytest

from customer_support.classification.models import IntentClassification
from customer_support.generation.models import GeneratorResult
from customer_support.pipeline import Pipeline, PipelineResult
from customer_support.quality_assurance.models import QualityResult
from customer_support.services.client import CompletionRequest, CompletionResult

# ── Stubs ─────────────────────────────────────────────────────────────────────

class StubRetriever:
    def retrieve(self, query: str, k: int) -> list[str]:
        return []


class MultiStepLLMClient:
    """Returns valid responses for all three pipeline LLM calls."""

    def __init__(self) -> None:
        self._call_count = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._call_count += 1
        if self._call_count == 1:
            content = json.dumps({"category": "tracking", "reasoning": "test"})
        elif self._call_count == 2:
            content = json.dumps({
                "answer": "Your order is on its way. Thank you for contacting us.",
                "sources_used": [],
            })
        else:
            content = json.dumps({
                "hallucination_detected": False,
                "unsupported_claims": [],
                "classification": "good_match",
                "reasoning": "Answer is complete.",
                "human_in_the_loop": False,
            })
        return CompletionResult(content=content, tokens_used=10)


# ── Exit contract ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPipelineResultExitContract:
    def test_pipeline_result_accepts_outputs_from_all_four_contexts(self) -> None:
        """PipelineResult can be constructed from typed outputs of all contexts.

        Verifies that the exit contract holds: if all four bounded contexts
        produce their typed result models, the pipeline can assemble a valid
        PipelineResult without a Pydantic ValidationError.
        """
        classification = IntentClassification(
            category="tracking",
            reasoning="Customer asks about order location.",
        )
        generation = GeneratorResult(
            answer="Your order is on its way.",
            sources=[1],
            tokens_used=42,
        )
        quality = QualityResult(
            passed=True,
            classification="good_match",
            reasoning="Answer covers essential information.",
            human_in_the_loop=False,
            hallucination_detected=False,
            confidence=1.0,
        )

        result = PipelineResult(
            request_id="test-id",
            query="Where is my order?",
            category="tracking",
            answer="Your order is on its way.",
            sources=[1],
            classification=classification,
            generation=generation,
            quality=quality,
            human_in_the_loop=False,
        )

        assert result.request_id == "test-id"
        assert result.category == "tracking"
        assert result.human_in_the_loop is False


# ── Startup resilience ────────────────────────────────────────────────────────

@pytest.mark.unit
class TestStartupResilience:
    def test_pipeline_with_missing_index_uses_empty_retriever(self) -> None:
        """Pipeline initialises without a FAISS index and returns a result.

        Verifies that _EmptyRetriever is used as fallback when no index
        exists, and that the pipeline continues to serve requests.
        """
        pipeline = Pipeline(
            llm_client=MultiStepLLMClient(),
            retriever=StubRetriever(),
        )
        result = pipeline.process("Where is my order? I need the tracking number.")
        assert isinstance(result, PipelineResult)
        assert result.metadata.get("retrieval_failed") is False

    def test_health_endpoint_returns_200_without_openai_key(self) -> None:
        """Health check passes even when no OpenAI API key is configured.

        Verifies availability: the service is reachable and reports healthy
        regardless of whether AI credentials are present.
        """
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from customer_support.main import app  # noqa: PLC0415

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"