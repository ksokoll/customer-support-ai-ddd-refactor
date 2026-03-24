# core/models.py
"""Shared Pydantic schemas: pipeline entry contract only.

core/ has no internal imports. PipelineResult lives in pipeline.py
where imports from all bounded contexts are permitted.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from ulid import ULID


class CustomerQuery(BaseModel):
    """Entry contract: validated input arriving at the pipeline."""

    query_id: str = Field(default_factory=lambda: str(ULID()))
    text: str = Field(..., min_length=10, max_length=1000)
    channel: Literal["email", "chat", "web"] = "web"
    language: str = "en"
    timestamp: datetime = Field(default_factory=datetime.now)


class PromptTemplate(BaseModel):
    """Versioned prompt definition.

    Prompt changes are content commits, not code changes.
    Each context imports its prompt as a PromptTemplate instance.

    Args:
        name: Short identifier (e.g. "classification").
        version: Semantic version string (e.g. "1.0.0").
        prompt: Full prompt text.
        last_modified: Date of last content change.
        tested_models: Models this prompt has been validated against.
        description: One-line description of what the prompt does.
    """

    name: str
    version: str
    prompt: str
    last_modified: datetime
    tested_models: list[str]
    description: str = ""