# Refactor Priorities: customer-support-ai

## Strengths

**Domain models are cleanly separated.** `models.py` with `CustomerQuery`, `IntentClassification`, and `Response` as Pydantic models is exactly right. These are proper domain objects, not plain dicts.

**Pipeline orchestrator pattern is in place.** `pipeline.py` knows the order of steps but not their implementation. This is the correct approach for an Application Service in DDD.

**Configuration is external and typed.** Pydantic `Settings` with `.env` is clean. Defined once, imported everywhere.

**Separation of concerns at the file level.** Each component (Classifier, Retriever, Generator, QualityCheck, AnswerJudge) has its own file. Structurally, this already gestures toward Bounded Contexts.

**Rate limiting as a separate concern.** Not mixed into the pipeline, lives in its own file. Correct.

---

## Weaknesses

Concrete refactor targets, ordered by priority.

**1. No Protocols or Interfaces anywhere.** This is the biggest issue. Instead of real swappability, every class contains the same `if settings.llm_provider == "openai": ... elif settings.llm_provider == "anthropic":` pattern. This is copy-paste polymorphism, not design. Adding a third provider requires changes in four files. A single `LLMClientProtocol` with `complete()` and `embed()` would reduce that to one place.

**2. Infrastructure instantiated inside the Domain.** `OpenAI()` is directly instantiated in `IntentClassifier.__init__()`, `ResponseGenerator.__init__()`, `QualityChecker.__init__()`, and `AnswerJudge.__init__()`. Domain classes must not instantiate API clients. The client must be injected (Dependency Injection), not self-built.

**3. Two retrievers without a shared contract.** `KnowledgeRetriever` and `BlobKnowledgeRetriever` both implement `retrieve()`, but there is no `RetrieverProtocol`. The pipeline hardcodes `BlobKnowledgeRetriever` directly. This means: to run locally, you need Azure credentials.

**4. No Bounded Contexts.** Everything lives flat in `src/`. In DDD terms, Classification, Retrieval, Generation, and Quality Assurance are four distinct Bounded Contexts with different lifecycles and responsibilities. The current structure does not reflect this.

**5. `answer_judge.py` and `quality_check.py` are cut incorrectly.** `QualityChecker` instantiates `AnswerJudge` directly (tight coupling, not testable) and also performs LLM calls itself. The technical checks (length, coherence) are pure domain logic with no I/O. The LLM calls are infrastructure. These are not separated.

**6. Config bug.** `config.py` mixes both `class Config:` and an inline `model_config` dict simultaneously. This is Pydantic v1 and v2 syntax mixed together. `blob_connection_string` has no default value, causing a crash on startup without a `.env` file and no helpful error message.

**7. `DEBUG` print statements in production code.** Present in `classifier.py` (`DEBUG - Raw API response`) and `rate_limiter.py` (`DEBUG - IP`, `DEBUG - BLOCKED!`). These need to be removed or replaced with a proper logger setup.

**8. Bare `except Exception` in `retriever_blob.py`.** Explicitly violates the style guide. Should be split into specific Azure and JSON exceptions at minimum.

**9. No tests, no `pyproject.toml`, no ADRs.** This is the Definition-of-Done gap. Without tests, the >85% coverage target is unreachable.

**10. Global instance in `rate_limiter.py`.** `rate_limiter = RateLimiter(...)` at module level creates untestable code and a global state side effect on import.

---

## Prioritization Summary

Points 1, 2, and 3 are interconnected and form the core of the DDD refactor. Points 4 and 5 are the structural work. Points 6 through 10 are cleanup that can be done in parallel or addressed first.

**starting point:** Sketching the Bounded Context structure first (Point 4), then derive where the Protocols need to live (Points 1, 2, 3). Everything else follows from there.