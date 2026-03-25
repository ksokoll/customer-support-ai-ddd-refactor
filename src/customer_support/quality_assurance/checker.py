# quality_assurance/checker.py
"""Technical quality checks for generated responses.

All functions in this module are pure: no I/O, no LLM calls, no side effects.
They can be unit-tested without any mocks or fixtures.

Semantic quality (hallucination, answer classification, HITL decision)
is handled by AnswerJudge in judge.py via a single LLM call.
"""

import re

from customer_support.core.config import settings


def check_coherence(answer: str) -> dict[str, object]:
    """Check whether a response is coherent and minimally well-structured.

    A response is coherent if it ends with punctuation, contains at least
    two distinct sentences, and does not repeat any sentence verbatim.

    Args:
        answer: Generated response string.

    Returns:
        Dict with keys:
            passed (bool): True if all coherence checks pass.
            issues (list[str]): List of issue descriptions if any failed.
    """
    issues: list[str] = []

    if not answer.strip().endswith((".", "!", "?")):
        issues.append("Response does not end with punctuation.")

    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip()]

    if len(sentences) < settings.min_response_sentences:
        issues.append("Response is too short or lacks sentence structure.")

    if len(sentences) != len(set(sentences)):
        issues.append("Response contains repeated sentences.")

    return {"passed": len(issues) == 0, "issues": issues}


def check_length(answer: str) -> dict[str, object]:
    """Check whether a response is within the acceptable word count range.

    Args:
        answer: Generated response string.

    Returns:
        Dict with keys:
            passed (bool): True if word count is within [20, 200].
            word_count (int): Actual word count.
            issue (str | None): Description of the issue if check failed.
    """
    word_count = len(answer.split())

    if word_count < settings.min_response_words:
        return {
            "passed": False,
            "word_count": word_count,
            "issue": (
                f"Response too short "
                f"({word_count} words, minimum {settings.min_response_words})."
            ),
        }

    if word_count > settings.max_response_words:
        return {
            "passed": False,
            "word_count": word_count,
            "issue": (
                f"Response too long "
                f"({word_count} words, maximum {settings.max_response_words})."
            ),
        }

    return {"passed": True, "word_count": word_count, "issue": None}