# tests/conftest.py
"""Shared fixtures and stubs for all test levels.

Stubs here are available to unit, integration, and e2e tests.
Import them in test files via pytest fixture injection or direct import.
"""

import json

import pytest

from customer_support.services.client import CompletionRequest, CompletionResult

# ── Reusable LLM stubs ────────────────────────────────────────────────────────

class StubLLMClient:
    """Configurable stub returning a preset string or JSON response.

    Args:
        content: String returned as completion content. Pass a dict
                 and it will be serialized to JSON automatically.
        tokens_used: Token count to report in CompletionResult.
    """

    def __init__(self, content: str | dict, tokens_used: int = 10) -> None:
        self._content = json.dumps(content) if isinstance(content, dict) else content
        self._tokens_used = tokens_used

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content=self._content, tokens_used=self._tokens_used)


class MalformedLLMClient:
    """Stub returning content that cannot be parsed as JSON."""

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="not valid json {{", tokens_used=0)


class FailingLLMClient:
    """Stub that always raises RuntimeError."""

    def complete(self, request: CompletionRequest) -> CompletionResult:
        raise RuntimeError("simulated API failure")


class EmptyLLMClient:
    """Stub returning an empty string."""

    def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(content="", tokens_used=0)


# ── Pytest fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def stub_llm_client():
    """Default StubLLMClient returning a generic string response."""
    return StubLLMClient(content="[StubLLMClient] default response")


@pytest.fixture()
def failing_llm_client():
    return FailingLLMClient()


@pytest.fixture()
def empty_llm_client():
    return EmptyLLMClient()