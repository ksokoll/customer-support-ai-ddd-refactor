# quality_assurance/models.py
"""Pydantic schema for quality assurance output."""
from typing import Literal

from pydantic import BaseModel


class QualityResult(BaseModel):
    """Result of the three-step LLM-as-Judge evaluation."""

    passed: bool
    classification: Literal["no_match", "mediocre_match", "good_match"]
    reasoning: str
    human_in_the_loop: bool
    hallucination_detected: bool
    confidence: float
