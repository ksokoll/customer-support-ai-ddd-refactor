# generation/models.py
"""Pydantic schema for generation output."""
from pydantic import BaseModel, Field


class GeneratorResult(BaseModel):
    """Result of generating a customer support response.

    sources contains the integer indices of context blocks the model drew
    from (as reported in sources_used in the JSON response). Formatting
    to "Source 1", "Source 2" etc. belongs in the presentation layer.
    """

    answer: str
    sources: list[int] = Field(default_factory=list)
    tokens_used: int = 0