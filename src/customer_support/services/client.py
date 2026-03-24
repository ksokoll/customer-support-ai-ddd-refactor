# services/client.py
"""AI client abstractions.

Defines two Protocols that all AI client implementations must satisfy:
- LLMClient: text generation and JSON-structured completions
- EmbeddingClient: vector embedding generation

These are kept separate because their signatures and consumers differ.
Collapsing them into one Protocol would be a forced abstraction.

All bounded contexts depend on these Protocols, never on a concrete
client. Swapping providers requires only a new implementation here.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ── Request / Result types ────────────────────────────────────────────────────

class CompletionRequest(BaseModel):
    """Parameters for a single LLM completion call.

    Carries all call-site-specific overrides so that LLMClient.complete()
    has a stable, typed signature without **kwargs catch-alls.
    """

    system: str
    user: str
    temperature: float = Field(default=0.3)
    response_format: dict[str, Any] | None = Field(default=None)
    max_tokens: int = Field(default=500)


class CompletionResult(BaseModel):
    """Result of a single LLM completion call."""

    content: str
    tokens_used: int = 0


# ── Protocols ─────────────────────────────────────────────────────────────────

@runtime_checkable
class LLMClient(Protocol):
    """Minimal interface every text-generation client must satisfy.

    Used by: IntentClassifier, ResponseGenerator, AnswerJudge.
    """

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Generate a completion for the given prompt pair.

        Args:
            request: Typed completion parameters including system prompt,
                user message, temperature, response format, and token limit.

        Returns:
            CompletionResult with the model response and token usage.

        Raises:
            RuntimeError: If the underlying API call fails.
        """
        ...


@runtime_checkable
class EmbeddingClient(Protocol):
    """Minimal interface every embedding client must satisfy.

    Used by: FAISSRetriever, BlobRetriever, store_builder.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a list of texts.

        Args:
            texts: List of strings to embed. Must not be empty.

        Returns:
            List of float vectors, one per input text.
            Vector dimensionality is model-dependent.

        Raises:
            RuntimeError: If the underlying API call fails.
        """
        ...


# ── Dummy implementations (local dev + unit tests) ────────────────────────────

class DummyLLMClient:
    """Deterministic LLM client for local development and unit tests.

    Returns a static response without any external calls.
    Replace with OpenAIClient or AnthropicClient before deploying.
    """

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Return a static placeholder response.

        Args:
            request: Ignored except for echoing the first 80 chars of user.

        Returns:
            CompletionResult with placeholder content and zero token usage.
        """
        return CompletionResult(
            content=f"[DummyLLMClient] Received: {request.user[:80]}",
            tokens_used=0,
        )


class DummyEmbeddingClient:
    """Deterministic embedding client for local development and unit tests.

    Returns zero-vectors without any external calls. Sufficient for
    testing retrieval plumbing without real semantic similarity.
    """

    _DIMENSIONS: int = 1536  # matches text-embedding-3-small output size

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a list of zero-vectors matching input length.

        Args:
            texts: List of strings to embed.

        Returns:
            List of zero-vectors, one per input text.
        """
        return [[0.0] * self._DIMENSIONS for _ in texts]