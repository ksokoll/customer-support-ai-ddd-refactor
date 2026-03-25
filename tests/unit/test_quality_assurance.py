# tests/unit/test_quality_assurance.py
"""Unit tests for the Quality Assurance context.

checker.py: pure function tests — no mocks needed.
AnswerJudge: stub LLM client returning configurable JSON.
QualityChecker: stub AnswerJudge for isolation.
"""

import pytest

from customer_support.core.exceptions import QualityAssuranceError
from customer_support.quality_assurance.checker import check_coherence, check_length
from customer_support.quality_assurance.judge import AnswerJudge, QualityChecker
from customer_support.quality_assurance.models import QualityResult
from tests.conftest import FailingLLMClient, StubLLMClient


class StubAnswerJudge:
    """Stub AnswerJudge for QualityChecker isolation tests."""

    def __init__(self, result: dict) -> None:
        self._result = result

    def evaluate(self, query: str, answer: str, context_docs: list[str]) -> dict:
        return self._result


def _good_judge_response() -> dict:
    return {
        "hallucination_detected": False,
        "unsupported_claims": [],
        "classification": "good_match",
        "reasoning": "Customer can resolve their issue.",
        "human_in_the_loop": False,
    }


# ── check_coherence (pure functions) ─────────────────────────────────────────

@pytest.mark.unit
class TestCheckCoherence:
    def test_passes_for_well_structured_response(self) -> None:
        result = check_coherence(
            "Your order is on its way. You will receive a tracking email shortly."
        )
        assert result["passed"] is True
        assert result["issues"] == []

    def test_fails_when_response_does_not_end_with_punctuation(self) -> None:
        result = check_coherence("Your order is on its way")
        assert result["passed"] is False
        assert any("punctuation" in i for i in result["issues"])

    def test_fails_when_response_is_single_sentence(self) -> None:
        result = check_coherence("Done.")
        assert result["passed"] is False

    def test_fails_when_response_contains_repeated_sentences(self) -> None:
        result = check_coherence(
            "Your order is on its way. Your order is on its way. Thank you!"
        )
        assert result["passed"] is False
        assert any("repeated" in i for i in result["issues"])


# ── check_length (pure functions) ─────────────────────────────────────────────

@pytest.mark.unit
class TestCheckLength:
    def test_passes_for_response_within_bounds(self) -> None:
        answer = " ".join(["word"] * 50)
        result = check_length(answer)
        assert result["passed"] is True
        assert result["word_count"] == 50

    def test_fails_when_response_is_too_short(self) -> None:
        result = check_length("Too short.")
        assert result["passed"] is False
        assert "short" in str(result["issue"]).lower()

    def test_fails_when_response_is_too_long(self) -> None:
        answer = " ".join(["word"] * 201)
        result = check_length(answer)
        assert result["passed"] is False
        assert "long" in str(result["issue"]).lower()

    def test_reports_correct_word_count(self) -> None:
        answer = " ".join(["word"] * 42)
        result = check_length(answer)
        assert result["word_count"] == 42


# ── AnswerJudge ───────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestAnswerJudge:
    def test_evaluate_returns_dict_with_required_keys(self) -> None:
        judge = AnswerJudge(client=StubLLMClient(_good_judge_response()))
        result = judge.evaluate("query", "answer", ["context"])
        assert all(k in result for k in [
            "hallucination_detected", "classification",
            "reasoning", "human_in_the_loop", "unsupported_claims",
        ])

    def test_evaluate_sets_hallucination_detected_true(self) -> None:
        response = _good_judge_response()
        response["hallucination_detected"] = True
        response["human_in_the_loop"] = True
        response["unsupported_claims"] = ["claim not in context"]
        judge = AnswerJudge(client=StubLLMClient(response))
        result = judge.evaluate("query", "answer", ["context"])
        assert result["hallucination_detected"] is True
        assert result["human_in_the_loop"] is True

    def test_evaluate_raises_on_llm_failure(self) -> None:
        judge = AnswerJudge(client=FailingLLMClient())
        with pytest.raises(QualityAssuranceError, match="LLM call failed"):
            judge.evaluate("query", "answer", ["context"])

    def test_evaluate_raises_on_missing_required_field(self) -> None:
        incomplete = {"hallucination_detected": False, "reasoning": "ok"}
        judge = AnswerJudge(client=StubLLMClient(incomplete))
        with pytest.raises(QualityAssuranceError, match="missing required field"):
            judge.evaluate("query", "answer", ["context"])


# ── QualityChecker ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestQualityChecker:
    def _make_checker(self, judge_result: dict) -> QualityChecker:
        judge = AnswerJudge(client=StubLLMClient(judge_result))
        return QualityChecker(judge=judge)

    def test_check_returns_quality_result(self) -> None:
        checker = self._make_checker(_good_judge_response())
        answer = " ".join(["word"] * 30) + "."
        result = checker.check("query", answer, ["context"])
        assert isinstance(result, QualityResult)

    def test_check_passes_when_technical_and_judge_pass(self) -> None:
        checker = self._make_checker(_good_judge_response())
        answer = (
            "Your order has been dispatched and is on its way to your address. "
            "You will receive a tracking email from our carrier within the next few hours. "
            "Thank you for shopping with StyleHub."
        )
        result = checker.check("query", answer, ["context"])
        assert result.passed is True
        assert result.human_in_the_loop is False

    def test_check_sets_human_in_the_loop_true_when_hallucination_detected(
        self,
    ) -> None:
        response = _good_judge_response()
        response["hallucination_detected"] = True
        response["human_in_the_loop"] = True
        checker = self._make_checker(response)
        answer = (
            "Your order has been dispatched and is on its way to your address. "
            "You will receive a tracking email from our carrier within the next few hours. "
            "Thank you for shopping with StyleHub."
        )
        result = checker.check("query", answer, ["context"])
        assert result.hallucination_detected is True
        assert result.human_in_the_loop is True

    def test_check_fails_when_classification_is_no_match(self) -> None:
        response = _good_judge_response()
        response["classification"] = "no_match"
        response["human_in_the_loop"] = True
        checker = self._make_checker(response)
        answer = (
            "Your order has been dispatched and is on its way to your address. "
            "You will receive a tracking email from our carrier within the next few hours. "
            "Thank you for shopping with StyleHub."
        )
        result = checker.check("query", answer, ["context"])
        assert result.passed is False

    def test_confidence_is_1_when_both_technical_checks_pass(self) -> None:
        checker = self._make_checker(_good_judge_response())
        answer = (
            "Your order has been dispatched and is on its way to your address. "
            "You will receive a tracking email from our carrier within the next few hours. "
            "Thank you for shopping with StyleHub."
        )
        result = checker.check("query", answer, ["context"])
        assert result.confidence == 1.0

    def test_confidence_is_reduced_when_coherence_fails(self) -> None:
        checker = self._make_checker(_good_judge_response())
        answer = " ".join(["word"] * 30)  # no trailing punctuation
        result = checker.check("query", answer, ["context"])
        assert result.confidence < 1.0