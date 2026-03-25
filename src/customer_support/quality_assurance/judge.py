# quality_assurance/judge.py
"""Quality Assurance context: LLM-as-Judge evaluation.

AnswerJudge executes a three-step evaluation in a single LLM call:
  Step 1: Fact check (hallucination detection)
  Step 2: Answer classification (no_match / mediocre_match / good_match)
  Step 3: HITL decision (escalation triggers)

QualityChecker composes the pure technical checks from checker.py with
the AnswerJudge. Both receive their dependencies via constructor injection.
"""

import json
import logging

from customer_support.core.config import settings
from customer_support.core.exceptions import QualityAssuranceError
from customer_support.quality_assurance.checker import check_coherence, check_length
from customer_support.quality_assurance.models import QualityResult
from customer_support.quality_assurance.prompts import JUDGE_PROMPT
from customer_support.services.client import CompletionRequest, LLMClient

logger = logging.getLogger(__name__)
_PROCESS_STEP = "quality_assurance"


class AnswerJudge:
    """LLM-as-Judge evaluator for response quality and HITL decisions.

    Executes a single LLM call with a three-step structured prompt.
    Receives LLMClient via constructor injection.

    Args:
        client: LLM client satisfying the LLMClient Protocol.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def evaluate(
        self,
        query: str,
        answer: str,
        context_docs: list[str],
    ) -> dict[str, object]:
        """Run three-step LLM-as-Judge evaluation.

        Args:
            query: Original customer query string.
            answer: Generated response to evaluate.
            context_docs: Retrieved documents used as ground truth.

        Returns:
            Dict with keys: hallucination_detected, unsupported_claims,
            classification, reasoning, human_in_the_loop.

        Raises:
            QualityAssuranceError: If the LLM call fails or returns
                malformed JSON.
        """
        context_block = "\n".join(
            f"[Source {i}]: {doc[:300]}" for i, doc in enumerate(context_docs, start=1)
        )
        user_prompt = (
            f"**Customer Query:**\n{query}\n\n"
            f"**AI Response:**\n{answer}\n\n"
            f"**Context (Ground Truth):**\n{context_block}\n\n"
            "Evaluate the AI response following the three-step process."
        )

        request = CompletionRequest(
            system=JUDGE_PROMPT.prompt,
            user=user_prompt,
            temperature=settings.temperature_judge,
            response_format={"type": "json_object"},
            max_tokens=settings.max_tokens_judge,
        )

        try:
            result = self._client.complete(request)
        except Exception as exc:
            raise QualityAssuranceError(
                f"LLM call failed during judge evaluation: {exc}"
            ) from exc

        try:
            parsed = json.loads(result.content)
        except json.JSONDecodeError as exc:
            raise QualityAssuranceError(
                f"Judge response is not valid JSON: {result.content!r}"
            ) from exc

        try:
            return {
                "hallucination_detected": bool(parsed["hallucination_detected"]),
                "unsupported_claims": parsed.get("unsupported_claims", []),
                "classification": parsed["classification"],
                "reasoning": parsed.get("reasoning", ""),
                "human_in_the_loop": bool(parsed["human_in_the_loop"]),
            }
        except KeyError as exc:
            raise QualityAssuranceError(
                f"Judge response missing required field: {exc}"
            ) from exc


class QualityChecker:
    """Orchestrates technical checks and LLM-as-Judge evaluation.

    Technical checks (coherence, length) are pure functions with no I/O.
    Semantic evaluation is delegated to AnswerJudge.

    Both components are received via constructor injection so that
    QualityChecker can be unit-tested with a stub AnswerJudge.

    Args:
        judge: AnswerJudge instance for semantic evaluation.
    """

    def __init__(self, judge: AnswerJudge) -> None:
        self._judge = judge

    def check(
        self,
        query: str,
        answer: str,
        context_docs: list[str],
    ) -> QualityResult:
        """Run all quality checks and return a typed QualityResult.

        Technical checks run first (no I/O). If they fail, the judge
        still runs so that HITL can be set appropriately.

        Args:
            query: Original customer query string.
            answer: Generated response to evaluate.
            context_docs: Retrieved documents used as ground truth.

        Returns:
            QualityResult with all evaluation fields populated.

        Raises:
            QualityAssuranceError: If the judge evaluation fails.
        """
        coherence = check_coherence(answer)
        length = check_length(answer)

        technical_passed = bool(coherence["passed"]) and bool(length["passed"])
        confidence = self._calculate_confidence(
            coherence_passed=bool(coherence["passed"]),
            length_passed=bool(length["passed"]),
        )

        judge_result = self._judge.evaluate(query, answer, context_docs)

        overall_passed = technical_passed and judge_result["classification"] == "good_match"

        logger.info(
            "Quality check completed",
            extra={
                "process_step": _PROCESS_STEP,
                "passed": overall_passed,
                "classification": judge_result["classification"],
                "human_in_the_loop": judge_result["human_in_the_loop"],
                "hallucination_detected": judge_result["hallucination_detected"],
            },
        )

        return QualityResult(
            passed=overall_passed,
            classification=str(judge_result["classification"]),
            reasoning=str(judge_result["reasoning"]),
            human_in_the_loop=bool(judge_result["human_in_the_loop"]),
            hallucination_detected=bool(judge_result["hallucination_detected"]),
            confidence=confidence,
        )

    @staticmethod
    def _calculate_confidence(
        coherence_passed: bool,
        length_passed: bool,
    ) -> float:
        """Calculate a technical quality confidence score between 0.0 and 1.0.

        Args:
            coherence_passed: Whether the coherence check passed.
            length_passed: Whether the length check passed.

        Returns:
            Weighted confidence score. Coherence weight: 0.7, length: 0.3.
        """
        score = 0.0
        if coherence_passed:
            score += settings.confidence_weight_coherence
        if length_passed:
            score += settings.confidence_weight_length
        return round(score, 2)