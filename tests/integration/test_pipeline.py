# tests/integration/test_pipeline.py
"""Integration tests for the full Pipeline.

All tests use stub clients and a stub retriever.
No real API calls, no real FAISS index on disk.
"""

import json

import pytest

from customer_support.core.exceptions import GenerationError
from customer_support.pipeline import Pipeline, PipelineResult
from customer_support.services.client import CompletionRequest, CompletionResult

# ── Stubs ─────────────────────────────────────────────────────────────────────

class StubRetriever:
    """Returns a fixed list of context documents."""

    def __init__(self, docs: list[str] | None = None) -> None:
        self._docs = docs or ["Q: Where is my order?\nA: Log in and visit My Orders."]

    def retrieve(self, query: str, k: int) -> list[str]:
        return self._docs[:k]


class FailingRetriever:
    """Always raises RetrievalError."""

    def retrieve(self, query: str, k: int) -> list[str]:
        from customer_support.core.exceptions import RetrievalError
        raise RetrievalError("index not found")


class MultiStepLLMClient:
    """Returns different JSON responses per call to simulate the full pipeline.

    Call order:
      1. Classification  -> IntentClassification JSON
      2. Generation      -> plain text answer
      3. AnswerJudge     -> QualityResult JSON
    """

    def __init__(self) -> None:
        self._call_count = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._call_count += 1

        if self._call_count == 1:
            # Classification
            content = json.dumps({
                "category": "tracking",
                "reasoning": "Customer asks about order location.",
            })
        elif self._call_count == 2:
            # Generation — structured JSON
            content = json.dumps({
                "answer": (
                    "Your order is on its way. You can track it by logging into "
                    "your account and visiting My Orders. Thank you for contacting StyleHub."
                ),
                "sources_used": [1],
            })
        else:
            # AnswerJudge
            content = json.dumps({
                "hallucination_detected": False,
                "unsupported_claims": [],
                "classification": "good_match",
                "reasoning": "Answer covers the essential steps.",
                "human_in_the_loop": False,
            })

        return CompletionResult(content=content, tokens_used=20)


class FailingGenerationLLMClient:
    """Fails on the second call (generation step)."""

    def __init__(self) -> None:
        self._call_count = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._call_count += 1
        if self._call_count == 1:
            return CompletionResult(
                content=json.dumps({"category": "other", "reasoning": "test"}),
                tokens_used=5,
            )
        raise RuntimeError("generation API failure")


class FailingJudgeLLMClient:
    """Fails on the third call (judge step)."""

    def __init__(self) -> None:
        self._call_count = 0

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self._call_count += 1
        if self._call_count == 1:
            return CompletionResult(
                content=json.dumps({"category": "other", "reasoning": "test"}),
                tokens_used=5,
            )
        if self._call_count == 2:
            return CompletionResult(
                content=json.dumps({
                    "answer": (
                        "Your order is on its way. You can track it by logging into "
                        "your account and visiting My Orders. Thank you for contacting us."
                    ),
                    "sources_used": [1],
                }),
                tokens_used=20,
            )
        raise RuntimeError("judge API failure")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pipeline(**kwargs) -> Pipeline:
    defaults = {
        "llm_client": MultiStepLLMClient(),
        "retriever": StubRetriever(),
    }
    defaults.update(kwargs)
    return Pipeline(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestPipelineHappyPath:
    def test_process_returns_pipeline_result(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert isinstance(result, PipelineResult)

    def test_process_result_has_non_empty_answer(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.answer

    def test_process_result_category_matches_classification(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.category == "tracking"

    def test_process_result_has_request_id(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.request_id

    def test_process_result_has_processing_time(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.processing_time_ms >= 0

    def test_process_result_human_in_the_loop_false_on_good_response(self) -> None:
        pipeline = _make_pipeline()
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.human_in_the_loop is False


@pytest.mark.integration
class TestPipelineFallbackBehaviour:
    def test_retrieval_failure_does_not_crash_pipeline(self) -> None:
        pipeline = _make_pipeline(retriever=FailingRetriever())
        result = pipeline.process("Where is my order? I need tracking info.")
        assert isinstance(result, PipelineResult)

    def test_retrieval_failure_is_flagged_in_metadata(self) -> None:
        pipeline = _make_pipeline(retriever=FailingRetriever())
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.metadata.get("retrieval_failed") is True

    def test_generation_failure_raises_generation_error(self) -> None:
        pipeline = _make_pipeline(
            llm_client=FailingGenerationLLMClient(),
            retriever=StubRetriever(),
        )
        with pytest.raises(GenerationError):
            pipeline.process("Where is my order? I need tracking info.")

    def test_quality_assurance_failure_sets_human_in_the_loop_true(self) -> None:
        pipeline = _make_pipeline(
            llm_client=FailingJudgeLLMClient(),
            retriever=StubRetriever(),
        )
        result = pipeline.process("Where is my order? I need tracking info.")
        assert result.human_in_the_loop is True