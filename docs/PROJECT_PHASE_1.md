# Project Phase 1: Skeleton + Core + Services

## Goal

Transfer everything covered by `AI_Project_Template_V3` into the refactored
`customer-support-ai` structure. This phase produces a compilable, importable
skeleton with all Protocols defined and all Contexts stubbed — but no business
logic yet. Phase 2 migrates the actual logic context by context.

Reference documents: `BOUNDED_CONTEXTS.md`, `template_coverage.md`

---

## Step 1: Project Structure + Skeleton

**What:** Create the full folder structure, empty `__init__.py` files,
and class stubs in every context-local `models.py`. No logic, no imports
beyond `pydantic.BaseModel`.

**Why stubs now:** `core/models.py` will reference `IntentClassification`,
`GeneratorResult`, and `QualityResult` in `PipelineResult`. Without stubs,
those type references either block compilation or force temporary `Any`
fields that need a second pass.

**Deliverables:**

```
src/customer_support/
  core/
    __init__.py
    config.py               (empty for now)
    models.py               (empty for now)
    exceptions.py           (empty for now)
  services/
    __init__.py
    client.py               (empty for now)
  classification/
    __init__.py
    models.py               (stub: IntentClassification)
    classifier.py           (empty for now)
    prompts.py              (empty for now)
  retrieval/
    __init__.py
    models.py               (stub: no result type needed here)
    retriever.py            (empty for now)
    store_builder.py        (empty for now)
  generation/
    __init__.py
    models.py               (stub: GeneratorResult)
    generator.py            (empty for now)
    prompts.py              (empty for now)
  quality_assurance/
    __init__.py
    models.py               (stub: QualityResult)
    checker.py              (empty for now)
    judge.py                (empty for now)
    prompts.py              (empty for now)
  pipeline.py               (empty for now)
  main.py                   (empty for now)

tests/
  unit/
    __init__.py
  integration/
    __init__.py
  conftest.py

docs/
  decisions/
    ADR_TEMPLATE.md

data/
  .gitkeep

pyproject.toml
Dockerfile
Makefile
.env.example
BOUNDED_CONTEXTS.md
ARCHITECTURE.md
DEVLOG.md
```

**Stub format for context-local models.py:**

```python
# classification/models.py
from pydantic import BaseModel

class IntentClassification(BaseModel):
    pass
```

**Definition of Done:**
- `python -c "from customer_support.classification.models import IntentClassification"` exits 0
- Same check passes for `GeneratorResult` and `QualityResult`
- All `__init__.py` files exist (even if empty)

---

## Step 2: `pyproject.toml`, `Dockerfile`, `Makefile`

**What:** Adapt from template. Rename package from `app` to `customer_support`.
Add provider extras (`openai`, `anthropic`) and RAG dependencies (`faiss-cpu`,
`langchain-openai`, `azure-storage-blob`).

**Key changes vs. template:**

`pyproject.toml`:
- Package name: `customer_support`
- Add to dependencies: `python-ulid`, `faiss-cpu`, `langchain-openai`,
  `azure-storage-blob`, `langchain-community`
- Coverage `fail_under`: raise to `80` (template default is `70`)
- Coverage `omit`: add `src/customer_support/retrieval/store_builder.py`
  (build-time script, not on the serving path)

`Dockerfile`: rename `app` to `customer_support` in all COPY and CMD lines.

`Makefile`: carry over all targets from template (`lint`, `format`, `test`,
`test-unit`, `test-integration`, `docker-build`, `run`). Add `build-store`
target for running `store_builder.py` locally.

**Definition of Done:**
- `pip install -e ".[dev,openai]"` completes without errors
- `make lint` runs (may report errors, must not crash)
- `make test` runs (zero tests passing is fine at this stage)

---

## Step 3: `core/` — Config, Models, Exceptions

**What:** Implement the three shared modules. No context-specific logic.

### `core/config.py`
Pydantic v2 `BaseSettings`. Fields to include:

```
app_name, app_version
openai_api_key (optional)
llm_model_name          default: "gpt-4o-mini"
embedding_model_name    default: "text-embedding-3-small"
temperature_default     default: 0.3
temperature_judge       default: 0.0
max_tokens              default: 500
min_query_length        default: 10
max_query_length        default: 1000
retrieval_top_k         default: 3
vector_db_path          default: "data/vector_db"
enable_blob_retrieval   default: False
blob_connection_string  optional
blob_container_name     optional
knowledge_blob_name     default: "faq.jsonl"
```

All fields have defaults. No field causes a startup crash when `.env`
is absent.

### `core/exceptions.py`

```python
class ClassificationError(Exception): ...
class RetrievalError(Exception): ...
class GenerationError(Exception): ...
class QualityAssuranceError(Exception): ...
```

No logic. Convention: when adding a new bounded context, register its
exception here, not locally in the context.

### `core/models.py`
Two shared schemas plus forward references to context-local models:

```python
CustomerQuery       # entry contract: query_id, text, channel, language, timestamp
PipelineResult      # exit contract: request_id, query, category, answer, sources,
                    #   classification: IntentClassification,
                    #   quality: QualityResult,
                    #   human_in_the_loop: bool,
                    #   processing_time_ms, metadata
```

Import `IntentClassification`, `GeneratorResult`, `QualityResult` from their
context-local `models.py` stubs. These are already present from Step 1.

**Definition of Done:**
- `from customer_support.core.config import settings` exits 0 without `.env`
- `from customer_support.core.models import PipelineResult` exits 0
- `from customer_support.core.exceptions import GenerationError` exits 0

---

## Step 4: `services/client.py` — LLMClient + EmbeddingClient

**What:** Define both Protocols and their supporting Pydantic types.
Add `DummyLLMClient` and `DummyEmbeddingClient` for tests.

### Protocols

```python
class CompletionRequest(BaseModel):
    system: str
    user: str
    temperature: float = 0.3
    response_format: dict | None = None
    max_tokens: int = 500

class CompletionResult(BaseModel):
    content: str
    tokens_used: int

@runtime_checkable
class LLMClient(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult: ...

@runtime_checkable
class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### Dummy implementations

`DummyLLMClient.complete()`: returns `CompletionResult(content="[DummyLLMClient]", tokens_used=0)`.
`DummyEmbeddingClient.embed()`: returns a list of zero-vectors matching input length.
Both deterministic, no external calls, safe for unit tests.

**Definition of Done:**
- `isinstance(DummyLLMClient(), LLMClient)` is `True`
- `isinstance(DummyEmbeddingClient(), EmbeddingClient)` is `True`
- Both checks pass as unit tests in `tests/unit/test_protocols.py`

---

## Step 5: Context Migration — Retrieval

**What:** Migrate retrieval logic into `retrieval/retriever.py` and
`retrieval/store_builder.py`. Validate both Protocols against real code.

**Why first:** Retrieval is the only context that uses `EmbeddingClient`.
Migrating it first validates both Protocols (`LLMClient` is not needed here,
but `EmbeddingClient` is exercised fully) against real code. If the Protocol
signature does not fit, we catch it at Context 1, not Context 4.

### `retrieval/retriever.py`

```python
@runtime_checkable
class RetrieverProtocol(Protocol):
    def retrieve(self, query: str, k: int) -> list[str]: ...

class FAISSRetriever:     # local dev + tests, reads JSONL from disk
class BlobRetriever:      # production, reads JSONL from Azure Blob
```

Both implementations receive `EmbeddingClient` via constructor injection.
Neither instantiates an embedding client directly.

### `retrieval/store_builder.py`
One-time script. Receives `EmbeddingClient` via constructor injection.
Must use the same `EmbeddingClient` instance (and therefore the same model
name) as the `FAISSRetriever` that will read the store.

**Definition of Done:**
- `isinstance(FAISSRetriever(...), RetrieverProtocol)` is `True`
- `isinstance(BlobRetriever(...), RetrieverProtocol)` is `True`
- Unit test: `FAISSRetriever` returns empty list for unknown query
- Unit test: `FAISSRetriever` returns top-k results for known query (synthetic data)
- `DummyEmbeddingClient` is sufficient for all unit tests (no real API calls)

---

## Step 6: Context Migration — Classification

**What:** Migrate `classifier.py` into `classification/classifier.py`.
Prompt into `classification/prompts.py`. Expand `IntentClassification` stub.

**Changes vs. original:**
- `OpenAI()` instantiation removed. `LLMClient` injected via constructor.
- `if settings.llm_provider == "openai":` branching removed. One call path
  via `CompletionRequest`.
- `_clean_json_response` removed. JSON parsing handled by `response_format`
  in `CompletionRequest`.
- `IntentClassification` stub in `classification/models.py` gets real fields:
  `category: Literal[...]`, `reasoning: str`.

**Definition of Done:**
- Unit test: classifier returns `IntentClassification` for known query
  (DummyLLMClient returning valid JSON)
- Unit test: classifier raises `ClassificationError` on malformed JSON response
- No `openai` import anywhere in `classification/`

---

## Step 7: Context Migration — Generation

**What:** Migrate `generator.py` into `generation/generator.py`.
Prompt into `generation/prompts.py`. Expand `GeneratorResult` stub.

**Changes vs. original:**
- `OpenAI()` instantiation removed. `LLMClient` injected.
- `_format_context` and `_extract_citations` remain as private methods.
- Token usage tracked via `CompletionResult.tokens_used`.
- `GeneratorResult` stub gets real fields: `answer: str`, `sources: list[str]`,
  `tokens_used: int`.

**Definition of Done:**
- Unit test: generator returns `GeneratorResult` with non-empty answer
- Unit test: generator raises `GenerationError` on empty client response
- Unit test: `_extract_citations` correctly extracts `[Source: 1]` markers
  (pure function test, no mock needed)

---

## Step 8: Context Migration — Quality Assurance

**What:** Migrate and restructure quality assurance into `checker.py` and
`judge.py`. Expand `QualityResult` stub.

**Changes vs. original:**
- `_check_hallucination` LLM call removed from `checker.py`.
  `checker.py` contains only pure functions: `check_coherence`, `check_length`.
- `AnswerJudge` receives `LLMClient` via constructor injection.
- `QualityChecker` receives `AnswerJudge` via constructor injection.
  Neither instantiates its dependencies.
- Three-step judge prompt implemented in `quality_assurance/prompts.py`.
- `QualityResult` stub gets real fields: `passed: bool`, `classification: str`,
  `reasoning: str`, `human_in_the_loop: bool`, `hallucination_detected: bool`,
  `confidence: float`.

**Definition of Done:**
- Unit test: `check_coherence` fails on single-sentence response (no mock)
- Unit test: `check_length` fails on response under 20 words (no mock)
- Unit test: judge returns `QualityResult` with `hallucination_detected=True`
  when DummyLLMClient returns matching JSON
- Unit test: judge sets `human_in_the_loop=True` when `hallucination_detected=True`
- No `openai` import anywhere in `quality_assurance/`

---

## Step 9: `pipeline.py` + `main.py`

**What:** Wire all contexts into the pipeline. Implement error handling
strategy from `BOUNDED_CONTEXTS.md`. Adapt `main.py` from template.

**Pipeline error handling:**

| Exception | Strategy |
|---|---|
| `ClassificationError` | Fallback to `"other"`, continue |
| `RetrievalError` | Continue with empty context, flag in metadata |
| `GenerationError` | Re-raise as HTTP 500 |
| `QualityAssuranceError` | Set `human_in_the_loop=True`, return answer |

**Definition of Done:**
- Integration test: full pipeline returns `PipelineResult` with
  `DummyLLMClient` and `DummyEmbeddingClient` (no external calls)
- Integration test: `RetrievalError` in retriever does not crash pipeline
- `make run` starts the server and `GET /health` returns 200

---

## Phase 1 Complete: Definition of Done

- [ ] Full folder structure with all `__init__.py` files
- [ ] `pyproject.toml` with correct package name and all dependencies pinned
- [ ] `make lint` passes (ruff + mypy)
- [ ] `make test-unit` passes
- [ ] `make test-integration` passes (DummyClients, no external calls)
- [ ] `make run` starts server, `/health` returns 200
- [ ] No `openai.OpenAI()` instantiation outside `services/client.py`
- [ ] No `if settings.llm_provider` branching in any bounded context
- [ ] `BOUNDED_CONTEXTS.md` and this file committed alongside the code
- [ ] `DEVLOG.md` updated with session notes