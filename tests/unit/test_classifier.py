# tests/unit/test_classifier.py
"""Unit tests for the Classification context."""

import pytest

from customer_support.classification.classifier import IntentClassifier
from customer_support.classification.models import IntentClassification
from customer_support.core.exceptions import ClassificationError
from tests.conftest import FailingLLMClient, MalformedLLMClient, StubLLMClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_classifier(category: str, reasoning: str = "test") -> IntentClassifier:
    return IntentClassifier(
        client=StubLLMClient({"category": category, "reasoning": reasoning})
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestIntentClassifierReturnsCorrectCategory:
    @pytest.mark.parametrize("category", [
        "tracking", "return", "product", "billing", "other"
    ])
    def test_classifier_returns_intent_classification_for_valid_category(
        self, category: str
    ) -> None:
        classifier = _make_classifier(category)
        result = classifier.classify("where is my order?")
        assert isinstance(result, IntentClassification)
        assert result.category == category

    def test_classifier_preserves_reasoning_from_response(self) -> None:
        classifier = IntentClassifier(
            client=StubLLMClient({
                "category": "tracking",
                "reasoning": "Customer asks about order location",
            })
        )
        result = classifier.classify("where is my order?")
        assert result.reasoning == "Customer asks about order location"

    def test_classifier_accepts_empty_reasoning(self) -> None:
        classifier = IntentClassifier(
            client=StubLLMClient({"category": "billing", "reasoning": ""})
        )
        result = classifier.classify("when is my refund?")
        assert result.reasoning == ""


@pytest.mark.unit
class TestIntentClassifierErrorHandling:
    def test_classifier_raises_classification_error_on_malformed_json(
        self,
    ) -> None:
        classifier = IntentClassifier(client=MalformedLLMClient())
        with pytest.raises(ClassificationError, match="not valid JSON"):
            classifier.classify("some query")

    def test_classifier_raises_classification_error_on_llm_failure(
        self,
    ) -> None:
        classifier = IntentClassifier(client=FailingLLMClient())
        with pytest.raises(ClassificationError, match="LLM call failed"):
            classifier.classify("some query")

    def test_classifier_raises_classification_error_on_missing_category_field(
        self,
    ) -> None:
        classifier = IntentClassifier(
            client=StubLLMClient({"reasoning": "no category here"})
        )
        with pytest.raises(ClassificationError, match="missing required fields"):
            classifier.classify("some query")