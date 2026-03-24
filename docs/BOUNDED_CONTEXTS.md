# Bounded Contexts

## Overview

The application is structured around four bounded contexts plus shared
cross-cutting infrastructure. The Knowledge Engineering side (Context 1)
handles vector store construction and knowledge management. The Request
Serving side (Contexts 2-4) processes incoming customer queries through
classification, generation, and quality assurance.

```
[Knowledge Engineering]                    [Request Serving]

retrieval/                data/             pipeline.py
  store_builder.py  →     vector_store  →    classification/classifier.py
  retriever.py            (contract)    →    retrieval/retriever.py
                                        →    generation/generator.py
                                        →    quality_assurance/checker.py
                                                              /judge.py
```

The FAISS vector store in `data/` is the contract between the two sides.
Knowledge Engineering writes it; Request Serving reads it.

Two Protocols in `services/` are the contracts between all domain contexts
and their AI infrastructure (see ADR-002):
- `LLMClient`: text generation and JSON-structured completions
- `EmbeddingClient`: vector embedding generation

**Deliberate trade-off — granularity vs. project size:**
This structure results in 12-15 files for approximately 500-700 lines of
business logic. Several files will contain only 30-50 lines. This is
accepted in exchange for clear boundary enforcement and independent
testability per context, which is more important for enterprise automations, which might contain more code, than to minimize file count.

---

## Context 1: Retrieval (Domain Logic + Infrastructure)

**Responsibility:** Build the FAISS vector store from the JSONL knowledge
base, and retrieve relevant Q&A pairs at serving time.

**Modules:**
- `retrieval/retriever.py`: `RetrieverProtocol` definition, `FAISSRetriever`,
  `BlobRetriever`
- `retrieval/store_builder.py`: One-time FAISS index construction from JSONL

**Key properties:**
- `RetrieverProtocol` defines a single method: `retrieve(query: str, k: int) -> list[str]`.
  All retriever implementations must satisfy this Protocol. The pipeline
  never imports a concrete retriever directly (ADR-002).
- `FAISSRetriever` reads from a local JSONL file. Used in local development
  and tests.
- `BlobRetriever` reads from Azure Blob Storage. Used in production.
  Requires no changes to the pipeline to swap (ADR-003).
- Embedding generation uses `EmbeddingClient`, not `LLMClient`. Text
  generation and embedding generation are different responsibilities with
  different signatures and must not be collapsed into one Protocol.
- `store_builder.py` and `retriever.py` must use the same `EmbeddingClient`
  implementation and the same model name. Using different models at build
  time vs. retrieval time causes silent embedding skew: queries and
  documents will occupy different vector spaces and similarity scores
  will be meaningless. The shared `EmbeddingClient` instance is the
  single source of truth for embedding behaviour (ADR-004).
- `store_builder.py` is a one-time script, not part of the serving path.
  The API Docker image does not include this code.

**Boundary rule:** This context never imports from `classification/`,
`generation/`, or `quality_assurance/`. It returns plain strings, not
domain objects.

---

## Context 2: Classification (Domain Logic)

**Responsibility:** Classify incoming customer queries into one of five
intent categories: `tracking`, `return`, `product`, `billing`, `other`.

**Modules:**
- `classification/classifier.py`: `IntentClassifier` with injected `LLMClient`
- `classification/prompts.py`: Versioned classification prompt

**Key properties:**
- The classifier receives a `LLMClient` via constructor injection. It never
  instantiates an API client directly.
- Classification requires `response_format={"type": "json_object"}` and
  `temperature=0.3`. These are passed via `CompletionRequest` to the
  client (see `services/client.py` for the full signature).
- The classification prompt is versioned in `prompts.py`, not hardcoded
  in the classifier. Prompt changes do not require classifier changes.
- Output is a typed `IntentClassification` Pydantic model (`category`,
  `reasoning`), not a raw dict.

**Boundary rule:** This context never imports from `retrieval/`,
`generation/`, or `quality_assurance/`. Classification is a pure
input-to-label transformation.

---

## Context 3: Generation (Domain Logic)

**Responsibility:** Generate a grounded customer support response from
the query, its classification, and the retrieved context documents.

**Modules:**
- `generation/generator.py`: `ResponseGenerator` with injected `LLMClient`
- `generation/prompts.py`: Versioned generation prompt with tone guidelines

**Key properties:**
- The generator receives a `LLMClient` via constructor injection.
- Context documents are provided by the pipeline from the Retrieval
  context. The generator never calls the retriever directly.
- Generation requires `temperature=0.3`, `max_tokens=500`, and returns
  token usage for cost monitoring. These are expressed via `CompletionRequest`
  and `CompletionResult` (see `services/client.py`).
- Source citation extraction (`[Source: N]`) is a pure string operation,
  not an LLM call. It lives in `generator.py` as a private method.
- Output is a typed `GeneratorResult` Pydantic model (`answer`, `sources`,
  `tokens_used`), not a raw dict.

**Boundary rule:** This context never imports from `classification/`,
`retrieval/`, or `quality_assurance/`. It knows nothing about how context
was retrieved or how the response will be evaluated.

---

## Context 4: Quality Assurance (Domain Logic + Infrastructure)

**Responsibility:** Evaluate response quality and determine whether a
human agent must review the case before the answer is returned.

**Modules:**
- `quality_assurance/checker.py`: Technical checks (coherence, length).
  Pure functions. No I/O.
- `quality_assurance/judge.py`: `AnswerJudge` with injected `LLMClient`.
  Three-step LLM-as-Judge evaluation and HITL decision.
- `quality_assurance/prompts.py`: Versioned judge prompt with scoring rubric.

**Key properties:**
- Technical checks in `checker.py` are pure functions with no I/O. They
  can be unit-tested without any mocks.
- `AnswerJudge` in `judge.py` receives a `LLMClient` via constructor
  injection. It never instantiates an API client directly.
- The judge prompt executes three sequential evaluation steps:

  **Step 1 — Fact check:** Does the answer contain claims not supported
  by the context? Returns `hallucination_detected: bool` and a list of
  unsupported claims if true.

  **Step 2 — Classification:** `no_match` / `mediocre_match` / `good_match`
  based on how well the answer covers the essential information.

  **Step 3 — HITL decision:** Determines whether the case requires human
  review. `hallucination_detected: true` is always an escalation trigger,
  in addition to the existing triggers (no_match, frustrated customer,
  financial anomalies, etc.).

- The `_check_hallucination` LLM call from the original `quality_check.py`
  is intentionally removed. Fact-checking is now a step inside the judge
  prompt, not a separate API call. This reduces latency and cost by one
  LLM round-trip per request (ADR-005).
- All escalation triggers live in the judge prompt, not in Python
  conditionals. Changes to escalation policy require only a prompt update,
  not a code deployment.
- Output is a typed `QualityResult` Pydantic model (`passed`,
  `classification`, `reasoning`, `human_in_the_loop`,
  `hallucination_detected`, `confidence`).

**Boundary rule:** This context never imports from `classification/`,
`retrieval/`, or `generation/`. It receives query, answer, and context
documents as plain strings from the pipeline.

---

## Cross-Cutting: Services, Config, and Contracts

### `services/client.py`

Two Protocols for two distinct responsibilities:

**`LLMClient`:** Text generation. All LLM-calling components (Classifier,
Generator, AnswerJudge) depend on this Protocol. Signature:

```python
def complete(self, request: CompletionRequest) -> CompletionResult: ...
```

`CompletionRequest` carries: `system`, `user`, `temperature`,
`response_format`, `max_tokens`. `CompletionResult` carries: `content`,
`tokens_used`. This avoids `**kwargs` catch-alls and preserves full
type safety across all call sites.

**`EmbeddingClient`:** Vector embedding generation. Used exclusively by
`retrieval/`. Signature:

```python
def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Collapsing both into one Protocol would constitute a forced abstraction:
the signatures are incompatible and the consumers are different.

### `core/config.py`
Central environment-driven settings via pydantic-settings v2. Imported by
all contexts. Contains all model names, thresholds, and storage paths.
No context hardcodes configuration values.

### `core/models.py`
Pydantic schemas that are shared across contexts: `CustomerQuery` (the
entry contract for the pipeline) and `PipelineResult` (the exit contract
returned to the API). Context-specific result types live in their own
context to keep each boundary self-contained.

### `core/exceptions.py`
Domain exception classes (`ClassificationError`, `RetrievalError`,
`GenerationError`, `QualityAssuranceError`). Exceptions live in `core/`
rather than in their originating context because `pipeline.py` is the
single place that catches all of them to apply the fallback strategy. If
exceptions lived in their contexts, `pipeline.py` would need to import
from all four contexts just to reference exception types — a coupling with
no business logic justification.

**Convention:** When adding a new bounded context, register its exception
in `core/exceptions.py`. Do not define it locally in the context.

### Context-local models
Each context owns its own result type:

| File | Model |
|---|---|
| `classification/models.py` | `IntentClassification` |
| `generation/models.py` | `GeneratorResult` |
| `quality_assurance/models.py` | `QualityResult` |

---

## Error Handling Strategy

Each bounded context raises its own domain exception on failure.
The pipeline catches these and applies the following strategy:

| Failure point | Strategy |
|---|---|
| `ClassificationError` | Fallback to category `"other"`, continue pipeline |
| `RetrievalError` | Continue with empty context, flag in metadata |
| `GenerationError` | Propagate as HTTP 500, do not return partial answer |
| `QualityAssuranceError` | Fail safe: set `human_in_the_loop=True`, return answer |

The goal is graceful degradation where possible: a retrieval failure must
not prevent a response from being generated. A generation failure leaves
nothing to return and warrants a hard error.

---

## Fitness Functions

Automated checks that verify architectural characteristics are treated
as first-class artifacts:

| Check | Type | Enforces |
|---|---|---|
| Import boundary test: `classification/` does not import from `generation/` | Unit | Boundary rules |
| `FAISSRetriever` and `BlobRetriever` satisfy `RetrieverProtocol` | Unit | Protocol contract |
| `DummyLLMClient` satisfies `LLMClient` Protocol | Unit | Protocol contract |
| `DummyEmbeddingClient` satisfies `EmbeddingClient` Protocol | Unit | Protocol contract |
| Docker container starts cleanly with all required env vars | Smoke | Deployment readiness |
| `store_builder.py` and `retriever.py` use the same embedding model name | Config test | Embedding skew prevention |

---

## Dependency Rules

```
core/                   no internal imports
services/               may import from core/
classification/         may import from core/ and services/
retrieval/              may import from core/ and services/
generation/             may import from core/ and services/
quality_assurance/      may import from core/ and services/
pipeline.py             may import from all contexts; is the only module that does
main.py                 may import from pipeline.py and core/
```

No bounded context imports from another bounded context directly.
All cross-context communication is routed through `pipeline.py`.

---

## Adding a New Context

When a concern grows beyond a few hundred lines, or when it has a
meaningfully different dependency profile, extract it into a new bounded
context under `src/customer_support/`.

Rules for new contexts:
1. A context may import from `core/` and `services/`. It must not import
   from another context directly — route through `pipeline.py` instead.
2. New contexts get their own section in this file and at least one ADR
   in `docs/decisions/`.
3. Add pytest fixtures for the new context in `tests/conftest.py`.
4. `LLMClient` and `EmbeddingClient` are the only approved ways to call
   any AI provider. New contexts must not introduce direct API client
   imports.