# classification/classifier.py
"""Classification context: intent classification for customer queries."""

import json
import logging

from customer_support.classification.models import IntentClassification
from customer_support.classification.prompts import CLASSIFICATION_PROMPT
from customer_support.core.config import settings
from customer_support.core.exceptions import ClassificationError
from customer_support.services.client import CompletionRequest, LLMClient

logger = logging.getLogger(__name__)
_PROCESS_STEP = "classification"


class IntentClassifier:
    """Classify customer queries into one of five intent categories.

    Receives LLMClient via constructor injection. Never imports a
    concrete AI client directly.

    Args:
        client: LLM client satisfying the LLMClient Protocol.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def classify(self, query: str) -> IntentClassification:
        """Classify a customer query into an intent category.

        Args:
            query: Raw customer query string.

        Returns:
            IntentClassification with category and reasoning.

        Raises:
            ClassificationError: If the LLM call fails or returns
                malformed JSON.
        """
        request = CompletionRequest(
            system=CLASSIFICATION_PROMPT.prompt,
            user=query,
            temperature=settings.temperature_default,
            response_format={"type": "json_object"},
            max_tokens=settings.max_tokens_classification,
        )

        try:
            result = self._client.complete(request)
        except Exception as exc:
            raise ClassificationError(
                f"LLM call failed during classification: {exc}"
            ) from exc

        try:
            parsed = json.loads(result.content)
        except json.JSONDecodeError as exc:
            raise ClassificationError(
                f"Classification response is not valid JSON: {result.content!r}"
            ) from exc

        try:
            classification = IntentClassification(
                category=parsed["category"],
                reasoning=parsed.get("reasoning", ""),
            )
        except (KeyError, ValueError) as exc:
            raise ClassificationError(
                f"Classification response missing required fields: {exc}"
            ) from exc

        logger.info(
            "Query classified",
            extra={
                "process_step": _PROCESS_STEP,
                "category": classification.category,
            },
        )

        return classification