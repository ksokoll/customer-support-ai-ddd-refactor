# generation/models.py
"""Pydantic schema for generation output."""
from pydantic import BaseModel, Field


class GeneratorResult(BaseModel):
    """Result of generating a customer support response."""

    answer: str
    sources: list[str] = Field(default_factory=list)
    tokens_used: int = 0
