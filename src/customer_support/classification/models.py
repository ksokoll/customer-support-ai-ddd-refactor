# classification/models.py
"""Pydantic schema for classification output."""
from typing import Literal

from pydantic import BaseModel


class IntentClassification(BaseModel):
    """Result of classifying a customer query into an intent category."""

    category: Literal["tracking", "return", "product", "billing", "other"]
    reasoning: str