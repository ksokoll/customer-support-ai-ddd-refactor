# generation/generator.py
"""Generation context: grounded response generation from retrieved context."""

import logging
import re

from customer_support.core.config import settings
from customer_support.core.exceptions import GenerationError
from customer_support.generation.models import GeneratorResult
from customer_support.generation.prompts import GENERATION_PROMPT
from customer_support.services.client import CompletionRequest, LLMClient

logger = logging.getLogger(__name__)
_PROCESS_STEP = "generation"


class ResponseGenerator:
    """Generate grounded customer support responses from retrieved context.

    Receives LLMClient via constructor injection. Never imports a
    concrete AI client directly. Context documents are provided by the
    pipeline from the Retrieval context — this class never calls a
    retriever.

    Args:
        client: LLM client satisfying the LLMClient Protocol.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def generate(
        self,
        query: str,
        category: str,
        context_docs: list[str],
    ) -> GeneratorResult:
        """Generate a response grounded in the retrieved context documents.

        Args:
            query: Raw customer query string.
            category: Intent category string from the Classification context.
                The pipeline extracts this from IntentClassification before
                passing it here, keeping generation free of cross-context imports.
            context_docs: Retrieved document strings from the Retrieval
                context, ordered by relevance.

        Returns:
            GeneratorResult with the answer, extracted source citations,
            and token usage.

        Raises:
            GenerationError: If the LLM call fails or returns an empty
                response.
        """
        user_prompt = self._build_prompt(query, category, context_docs)

        request = CompletionRequest(
            system=GENERATION_PROMPT,
            user=user_prompt,
            temperature=settings.temperature_default,
            max_tokens=settings.max_tokens,
        )

        try:
            result = self._client.complete(request)
        except Exception as exc:
            raise GenerationError(
                f"LLM call failed during generation: {exc}"
            ) from exc

        if not result.content or not result.content.strip():
            raise GenerationError("LLM returned an empty response.")

        answer = result.content.strip()
        sources = self._extract_citations(answer)

        logger.info(
            "Response generated",
            extra={
                "process_step": _PROCESS_STEP,
                "category": category,
                "sources_count": len(sources),
                "tokens_used": result.tokens_used,
            },
        )

        return GeneratorResult(
            answer=answer,
            sources=sources,
            tokens_used=result.tokens_used,
        )

    def _build_prompt(
        self,
        query: str,
        category: str,
        context_docs: list[str],
    ) -> str:
        """Assemble the user prompt from query, category, and context.

        Args:
            query: Raw customer query string.
            category: Intent category string.
            context_docs: Retrieved document strings.

        Returns:
            Formatted user prompt string.
        """
        context_block = self._format_context(context_docs)
        return (
            f"Customer Query: {query}\n"
            f"Category: {category}\n\n"
            f"Relevant Knowledge Base:\n{context_block}\n\n"
            "Generate a helpful response following the tone guidelines."
        )

    @staticmethod
    def _format_context(docs: list[str]) -> str:
        """Format context documents with numbered source markers.

        Args:
            docs: List of document strings.

        Returns:
            Formatted string with [Source N] headers per document.
        """
        if not docs:
            return "(No context available)"
        return "\n".join(f"[Source {i}]\n{doc}" for i, doc in enumerate(docs, start=1))

    @staticmethod
    def _extract_citations(text: str) -> list[str]:
        """Extract [Source: N] citation markers from a response string.

        Pure string operation — no LLM call.

        Args:
            text: Generated response text.

        Returns:
            Deduplicated list of citation strings found in the text,
            e.g. ["Source 1", "Source 2"].
        """
        matches = re.findall(r"\[Source:?\s*(\d+)\]", text, re.IGNORECASE)
        seen: set[str] = set()
        citations: list[str] = []
        for m in matches:
            key = f"Source {m}"
            if key not in seen:
                seen.add(key)
                citations.append(key)
        return citations