# pipeline.py
"""Pipeline orchestration.

Wires together all four bounded contexts:
  Validation -> Classification -> Retrieval -> Generation -> Quality Assurance

Each context raises its own domain exception. The pipeline applies the
fallback strategy defined in BOUNDED_CONTEXTS.md:

  ClassificationError   -> fallback to category "other", continue
  RetrievalError        -> continue with empty context, flag in metadata
  GenerationError       -> re-raise, results in HTTP 500
  QualityAssuranceError -> fail safe: set human_in_the_loop=True, return answer

This is the only module that imports from all bounded contexts.
No bounded context imports from pipeline.py.
"""

import logging
import time

from pydantic import BaseModel, Field

from customer_support.classification.classifier import IntentClassifier
from customer_support.classification.models import IntentClassification
from customer_support.core.config import settings
from customer_support.core.exceptions import (
    ClassificationError,
    GenerationError,
    QualityAssuranceError,
    RetrievalError,
)
from customer_support.core.models import CustomerQuery
from customer_support.generation.generator import ResponseGenerator
from customer_support.generation.models import GeneratorResult
from customer_support.quality_assurance.judge import AnswerJudge, QualityChecker
from customer_support.quality_assurance.models import QualityResult
from customer_support.retrieval.retriever import RetrieverProtocol
from customer_support.services.client import (
    DummyEmbeddingClient,
    DummyLLMClient,
    EmbeddingClient,
    LLMClient,
)


class PipelineResult(BaseModel):
    """Exit contract: full result returned to the API layer.

    Defined here because pipeline.py is the only module permitted to
    import from all bounded contexts. core/models.py has no internal
    imports by convention (Dependency Rule).
    """

    request_id: str
    query: str
    category: str
    answer: str
    sources: list[int] = Field(default_factory=list)
    classification: IntentClassification
    generation: GeneratorResult
    quality: QualityResult
    human_in_the_loop: bool
    processing_time_ms: float = 0.0
    metadata: dict[str, object] = Field(default_factory=dict)

logger = logging.getLogger(__name__)
_PROCESS_STEP = "pipeline"

_FALLBACK_CLASSIFICATION = IntentClassification(
    category="other",
    reasoning="Fallback: classification failed.",
)


class _EmptyRetriever:
    """Fallback retriever used when no index is available.

    Returns an empty list for every query. The pipeline handles this
    gracefully via the RetrievalError fallback path. Run 'make build-store'
    to build a real index.
    """

    def retrieve(self, query: str, k: int) -> list[str]:  # noqa: ARG002
        return []


class Pipeline:
    """Orchestrates the full customer support request flow.

    Args:
        llm_client: LLM client for Classification, Generation, and
            Quality Assurance. Defaults to DummyLLMClient.
        embedding_client: Embedding client for Retrieval.
            Defaults to DummyEmbeddingClient.
        retriever: Retriever implementation. If None, FAISSRetriever is
            constructed from settings. Pass a stub for integration tests.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        embedding_client: EmbeddingClient | None = None,
        retriever: RetrieverProtocol | None = None,
    ) -> None:
        effective_llm: LLMClient = llm_client or DummyLLMClient()
        effective_emb: EmbeddingClient = embedding_client or DummyEmbeddingClient()

        self._classifier = IntentClassifier(client=effective_llm)
        self._generator = ResponseGenerator(client=effective_llm)
        self._judge = AnswerJudge(client=effective_llm)
        self._checker = QualityChecker(judge=self._judge)

        if retriever is not None:
            self._retriever: RetrieverProtocol = retriever
        else:
            # Default: in-memory stub retriever — no real index needed.
            # main.py is responsible for wiring a real retriever for production.
            from customer_support.retrieval.retriever import FAISSRetriever  # noqa: PLC0415
            try:
                self._retriever = FAISSRetriever(
                    embedding_client=effective_emb,
                    vector_db_path=settings.vector_db_path,
                )
            except Exception:
                # No index built yet — fall back to empty retriever.
                # Run 'make build-store' to populate the vector store.
                self._retriever = _EmptyRetriever()

        logger.info("Pipeline initialised", extra={"process_step": _PROCESS_STEP})

    def process(self, query_text: str) -> PipelineResult:
        """Process a raw customer query through the full pipeline.

        Args:
            query_text: Raw query string from the API layer.

        Returns:
            PipelineResult with answer, quality evaluation, and metadata.

        Raises:
            ValueError: If query_text fails length validation.
            GenerationError: If response generation fails (HTTP 500).
        """
        start = time.monotonic()

        query = CustomerQuery(text=query_text)

        logger.info(
            "Pipeline started",
            extra={"process_step": _PROCESS_STEP, "request_id": query.query_id},
        )

        # Step 1: Classification — fallback to "other" on failure
        classification = self._classify(query)

        # Step 2: Retrieval — continue with empty context on failure
        context_docs, retrieval_failed = self._retrieve(query.text)

        # Step 3: Generation — hard failure, propagate as HTTP 500
        generation = self._generate(query, classification, context_docs)

        # Step 4: Quality Assurance — fail safe on failure
        quality = self._evaluate_quality(query.text, generation.answer, context_docs)

        elapsed_ms = round((time.monotonic() - start) * 1000, 2)

        result = PipelineResult(
            request_id=query.query_id,
            query=query.text,
            category=classification.category,
            answer=generation.answer,
            sources=generation.sources,
            classification=classification,
            generation=generation,
            quality=quality,
            human_in_the_loop=quality.human_in_the_loop,
            processing_time_ms=elapsed_ms,
            metadata={
                "sources_count": len(context_docs),
                "tokens_used": generation.tokens_used,
                "retrieval_failed": retrieval_failed,
                "hallucination_detected": quality.hallucination_detected,
            },
        )

        logger.info(
            "Pipeline completed",
            extra={
                "process_step": _PROCESS_STEP,
                "request_id": query.query_id,
                "category": classification.category,
                "human_in_the_loop": quality.human_in_the_loop,
                "processing_time_ms": elapsed_ms,
            },
        )

        return result

    def _classify(self, query: CustomerQuery) -> IntentClassification:
        """Classify the query. Fall back to 'other' on ClassificationError."""
        try:
            return self._classifier.classify(query.text)
        except ClassificationError as exc:
            logger.warning(
                "Classification failed, falling back to 'other': %s",
                exc,
                extra={"process_step": _PROCESS_STEP},
            )
            return _FALLBACK_CLASSIFICATION

    def _retrieve(self, query_text: str) -> tuple[list[str], bool]:
        """Retrieve context documents. Return empty list on RetrievalError.

        Returns:
            Tuple of (context_docs, retrieval_failed flag).
        """
        try:
            docs = self._retriever.retrieve(query_text, k=settings.retrieval_top_k)
            return docs, False
        except RetrievalError as exc:
            logger.warning(
                "Retrieval failed, continuing with empty context: %s",
                exc,
                extra={"process_step": _PROCESS_STEP},
            )
            return [], True

    def _generate(
        self,
        query: CustomerQuery,
        classification: IntentClassification,
        context_docs: list[str],
    ) -> GeneratorResult:
        """Generate a response. Propagates GenerationError (hard failure)."""
        try:
            return self._generator.generate(
                query=query.text,
                category=classification.category,
                context_docs=context_docs,
            )
        except GenerationError:
            logger.error(
                "Generation failed",
                extra={"process_step": _PROCESS_STEP},
            )
            raise

    def _evaluate_quality(
        self,
        query: str,
        answer: str,
        context_docs: list[str],
    ) -> QualityResult:
        """Evaluate quality. Fail safe on QualityAssuranceError."""
        try:
            return self._checker.check(
                query=query,
                answer=answer,
                context_docs=context_docs,
            )
        except QualityAssuranceError as exc:
            logger.warning(
                "Quality check failed, defaulting to human_in_the_loop=True: %s",
                exc,
                extra={"process_step": _PROCESS_STEP},
            )
            return QualityResult(
                passed=False,
                classification="no_match",
                reasoning="Quality check failed — escalating as precaution.",
                human_in_the_loop=True,
                hallucination_detected=False,
                confidence=0.0,
            )