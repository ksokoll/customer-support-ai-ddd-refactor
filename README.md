# Customer Support AI: DDD Refactor

A production-grade customer support pipeline built with Retrieval-Augmented Generation,
LLM-as-Judge quality evaluation, and a Domain-Driven Design architecture.

This project is a full refactor of an earlier working prototype
([ksokoll/customer-support-ai](https://github.com/ksokoll/customer-support-ai)).
The original achieved an 86% automation rate. This version rebuilds the same system
with explicit architectural boundaries, Protocol-based dependency injection, and a
complete test suite, without changing what it does.

---

## Business Context

**StyleHub GmbH** receives 12,000+ customer inquiries per month across email, chat,
and web. Eight full-time agents handle routine questions that make up roughly 70% of
all inbound volume: order tracking, return policies, payment issues, product questions.

The system automates these at scale:

| Metric | Result |
|---|---|
| Automation rate | 86% of queries answered without human review |
| HITL escalation rate | 14% routed to human agents |
| Intent classification accuracy | 80.3% (102/127 correct) |
| Answer Judge decision accuracy | ~90% |
| Response time | ~10-12 seconds end-to-end |
| Estimated cost reduction | €180k annual service cost addressable |

---

## Architecture

The system is structured around four bounded contexts. Each context owns its logic,
its output schema, and its tests. No context imports from another context directly,
all cross-context communication is routed through `pipeline.py`.

```
Request
  │
  ▼
pipeline.py
  ├── classification/     Classify query into intent category
  ├── retrieval/          Retrieve top-3 relevant Q&A pairs from FAISS
  ├── generation/         Generate grounded response from context
  └── quality_assurance/  Three-step LLM-as-Judge evaluation + HITL decision
```

```
src/customer_support/
  core/                   CustomerQuery, exceptions, no internal imports
  services/               LLMClient + EmbeddingClient Protocols, OpenAI implementations
  classification/         IntentClassifier, prompt, models
  retrieval/              RetrieverProtocol, FAISSRetriever, BlobRetriever, store_builder
  generation/             ResponseGenerator, prompt, models
  quality_assurance/      check_coherence, check_length (pure), AnswerJudge, QualityChecker
  pipeline.py             Orchestration and fallback strategy
  main.py                 FastAPI entry point
```

### Protocol-based Dependency Injection

All AI clients are injected via two `runtime_checkable` Protocols defined in
`services/client.py`. No bounded context ever imports `OpenAI` directly.

```python
class LLMClient(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult: ...

class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Swapping from OpenAI to Anthropic or a local model requires implementing one of
these Protocols. Nothing else changes.

### Quality Assurance: Three-Step Judge

A single LLM call replaces three separate calls from the original prototype.
The judge prompt executes sequentially:

1. **Fact check** does the answer introduce claims not in the retrieved context?
2. **Classification** `no_match` / `mediocre_match` / `good_match`
3. **HITL decision** escalation triggers including hallucination, frustration signals,
   financial anomalies, and specialist-required cases

`hallucination_detected: true` always triggers escalation, regardless of classification.

### Fallback Strategy

The pipeline degrades gracefully per failure type:

| Failure | Strategy |
|---|---|
| ClassificationError | Fallback to category `"other"`, continue |
| RetrievalError | Continue with empty context, flag in metadata |
| GenerationError | Hard failure, HTTP 500 |
| QualityAssuranceError | Fail safe: `human_in_the_loop=True`, return answer |

---

## Key Decisions

Six Architecture Decision Records document the reasoning behind the major choices.
Selected highlights:

**ADR-002: Protocol-based client abstraction.** The original code instantiated
`OpenAI()` directly in four separate classes with copy-pasted provider branching.
Two `runtime_checkable` Protocols replace all of it. Every bounded context is now
testable without an API key.

**ADR-004: Direct faiss-cpu over LangChain.** The LangChain FAISS wrapper does four
things: embed, build `IndexFlatL2`, search, wrap in Document objects. Replacing it
with direct `faiss-cpu` calls removed ~15 transitive dependencies and made the
embedding pipeline fully transparent. A parallel `texts.json` file handles the
index-to-text mapping that LangChain hid behind its docstore.

**ADR-005: Hallucination check merged into Judge prompt.** The original made three
sequential LLM calls per request (coherence/hallucination check, answer classification,
HITL decision). One structured three-step prompt replaces all three, reducing latency
and cost per request by one round-trip.

Full ADRs in `docs/decisions/`.

---

## Quickstart

```bash
# Install
pip install -e ".[dev,openai]"

# Configure
cp .env.example .env
# Add your OPENAI_API_KEY

# Build vector store (requires faq.jsonl in data/)
make build-store

# Run
make run
# API at http://localhost:8000/docs
```

### Example Request

```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"query": "Where is my order? I need the tracking number."}'
```

### Example Response

```json
{
  "request_id": "01KMFX0G12VAAHJ2FNPWCHBN6W",
  "category": "tracking",
  "answer": "Tracking numbers are sent within 24-48 hours after order confirmation...",
  "classification": { "category": "tracking", "reasoning": "..." },
  "quality": {
    "passed": true,
    "classification": "good_match",
    "human_in_the_loop": false,
    "hallucination_detected": false,
    "confidence": 1.0
  },
  "human_in_the_loop": false,
  "processing_time_ms": 13285.62
}
```

---

## Development

```bash
make test-unit          # 51 unit tests, no I/O, runs in <2s
make test-integration   # 10 integration tests, DummyClients only
make lint               # ruff + mypy
make docker-build
```

### Test Strategy

```
80% unit tests      Pure domain logic per context, DummyClients, no external calls
15% integration     Full pipeline with StubClients, no real API calls
 5% e2e             Real API, run explicitly
```

Each bounded context has its own test file. Stubs are defined once in `tests/conftest.py`.

---

## What Changed vs. the Original

| Aspect | Original | This Refactor |
|---|---|---|
| Structure | 12 flat files in `src/` | 4 bounded contexts with explicit boundaries |
| AI client | `OpenAI()` in 4 classes | Protocol injection, one implementation per provider |
| Provider switching | `if llm_provider == "openai"` in every class | Implement one Protocol, nothing else changes |
| RAG dependency | LangChain + FAISS wrapper | Direct `faiss-cpu`, ~15 fewer transitive deps |
| Quality checks | 3 sequential LLM calls | 1 structured three-step judge prompt |
| Tests | None | 61 tests (51 unit, 10 integration) |
| Architecture docs | None | 6 ADRs, BOUNDED_CONTEXTS.md |

---

## Project Layout

```
src/customer_support/
  core/
    config.py               Pydantic-settings v2, all fields have defaults
    models.py               CustomerQuery (entry contract)
    exceptions.py           Domain exceptions per bounded context
  services/
    client.py               LLMClient + EmbeddingClient Protocols,
                            DummyClients, OpenAILLMClient, OpenAIEmbeddingClient
  classification/
    classifier.py           IntentClassifier
    prompts.py              Versioned classification prompt
    models.py               IntentClassification
  retrieval/
    retriever.py            RetrieverProtocol, FAISSRetriever, BlobRetriever
    store_builder.py        One-time FAISS index builder (not on serving path)
  generation/
    generator.py            ResponseGenerator
    prompts.py              Versioned generation prompt
    models.py               GeneratorResult
  quality_assurance/
    checker.py              check_coherence, check_length (pure functions)
    judge.py                AnswerJudge, QualityChecker
    prompts.py              Versioned three-step judge prompt
    models.py               QualityResult
  pipeline.py               Orchestration + fallback strategy + PipelineResult
  main.py                   FastAPI, lifespan, /process endpoint

docs/
  decisions/
    ADR-001.md              DDD refactor rationale
    ADR-002.md              Protocol-based client abstraction
    ADR-003.md              RetrieverProtocol with FAISSRetriever and BlobRetriever
    ADR-004.md              Direct faiss-cpu over LangChain
    ADR-005.md              Hallucination check merged into Judge prompt
    ADR-006.md              core/models.py split
  BOUNDED_CONTEXTS.md       Boundary rules, dependency matrix, fitness functions

tests/
  unit/                     Per-context unit tests, DummyClients
  integration/              Full pipeline, StubClients
  conftest.py               Shared stubs (single source of truth)
```
