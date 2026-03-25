# Format:

## [Topic Area]

### Insight as headline (Date)

**Context:** What was the situation, what was I trying to do?

**Problem:** What didn't work or was suboptimal?

**Solution:** What did I do instead, and why?

**Takeaway:** One sentence I'd apply immediately in the next project.

---

## RAG Refactor: Architecture Planning

### Bounded Contexts before Code (23.03.2026)

**Context:** Starting the DDD refactor of `customer-support-ai`. The existing
codebase had ~500-700 lines of working logic across 12 flat files in `src/`,
with no Protocols, OpenAI clients instantiated directly in every class, and
`if llm_provider == "openai"` branching copy-pasted four times.

**Problem:** The temptation was to start coding immediately — rename files,
move classes, and refactor as you go. But without a clear context boundary
definition upfront, you risk moving the same mess into a new folder structure.
A first draft of `BOUNDED_CONTEXTS.md` was written, reviewed against the
existing code and the `architecture.md` style guide, and caught three
non-trivial issues before a single line of production code was touched:
`LLMClient.complete(system, user) -> str` was too narrow (loses
`response_format`, temperature overrides, token tracking); the Embedding
abstraction was being collapsed into `LLMClient` incorrectly; and
`core/models.py` was on a path to becoming a God Module.

**Solution:** Full architecture session first, not a single line of code written. `BOUNDED_CONTEXTS.md` went
through two review rounds and one targeted rewrite before `PROJECT_PHASE1.md`
was written. The document now specifies four Bounded Contexts, two separate
Protocols (`LLMClient` with `CompletionRequest`/`CompletionResult`,
`EmbeddingClient`), a split of `core/models.py` into shared contracts vs.
context-local result types, and an explicit error handling strategy with
graceful degradation per failure point. ADRs are deliberately deferred until
the first smoke test passes — decisions may still change.

**Takeaway:** A `BOUNDED_CONTEXTS.md` written and reviewed before the first
file is created is cheaper than refactoring context boundaries mid-migration.

---

## RAG Refactor: Skeleton + Core + Context Migration

### Ownership Walkthroughs catch what Refactors miss (24.03.2026)

**Context:** Full skeleton and context migration in one session: `core/`, `services/client.py`, all four bounded contexts, `pipeline.py`, `main.py`, integration tests. Every context had Protocol-based injection and its own unit tests before the next context was started.

**Problem:** Two regressions slipped through despite 61/61 passing tests at each step. First: `generator.py` still referenced `classification.category` in a logger call after the signature change from `IntentClassification` to `category: str` — the logger line was outside the method signature and the rename didn't catch it. Second: three rounds of Ownership Walkthrough feedback caught stale imports, duplicate stubs across four test files, a deprecated FastAPI `on_event`, an unused `import struct`, LangChain dependencies that ADR-004 had declared removed, and `FAISSRetriever` imported directly in `pipeline.py` against ADR-003. None of these broke tests. All of them violated the documented architecture.

**Solution:** Each walkthrough finding was fixed before moving to the next step. The logger regression was caught via traceback, not static analysis — which is exactly why `make lint` (ruff + mypy) needs to run as a pre-push gate, not just during active development. Stubs were consolidated into `conftest.py` as the single source of truth. `PipelineResult` was moved to `pipeline.py` to restore the `core/` no-internal-imports rule. `response_model=PipelineResult` was added to the FastAPI endpoint so OpenAPI docs reflect the actual contract.

**Takeaway:** A refactor is not done when the tests pass — it is done when the code, the ADRs, and the architecture document all say the same thing.

---

## RAG Refactor: Architecture Decisions

### Removing LangChain saves more than build time (24.03.2026)

**Context:** The original retriever used `langchain_community.vectorstores.FAISS`. Integrating the new `EmbeddingClient` Protocol would have required an adapter translating between the two interfaces.

**Problem:** LangChain's FAISS wrapper does four things: call embed(), build `IndexFlatL2`, call `faiss.search()`, wrap results in `Document` objects. That is four lines of logic behind a dependency that pulls ~15 transitive packages into the Docker image and requires an adapter purely to satisfy LangChain's interface — not to solve a domain problem.

**Solution:** Replaced with direct `faiss-cpu` calls. The text-to-index mapping problem (FAISS returns integers, not strings) is solved with a parallel `list[str]` serialized as `texts.json` alongside the index file. Total: ~60 lines, no adapter, full Protocol injection, measurably smaller image.

**Takeaway:** If you are writing glue code to satisfy a dependency's interface rather than to solve a domain problem, that dependency is costing more than it provides.

## RAG Refactor: Code Quality Pass

### Green tests confirm behaviour — ownership walkthroughs confirm architecture (25.03.2026)

**Context:** Phase 1 was complete, all 60 tests green, lint clean, smoke test successful.
Systematic ownership walkthrough across all production files to find issues no test would
catch.

**Problem:** Ten issues across four categories. Magic Numbers: `max_tokens=400`, word
count boundaries, sentence minimum, and confidence weights were all hardcoded inline or
in module constants instead of `config.py`. Connascence of Algorithm: JSONL parsing
(`f"Q: {qa['query']}\nA: {qa['gold_answer']}"`) and FAISS index construction existed
identically in both `retriever.py` and `store_builder.py` — silent drift risk if one
changes. Structural: `BlobRetriever` validated config and checked the Azure import inside
`_build_from_blob`, meaning the class could be instantiated with invalid config and only
fail on first use. Output contract: `GeneratorResult.sources` was `list[str]` with
formatted strings like `"Source 1"` — the generator received clean integers and
immediately threw away the type information.

**Solution:** Config received six new fields for all tuneable quality thresholds.
Shared functions `_parse_qa_line`, `_parse_jsonl`, and `_build_faiss_index` extracted in
`retriever.py` and imported by `store_builder.py` — one place for each algorithm.
`BlobRetriever.__init__` now validates config and checks the import, failing fast before
any work starts. `except Exception` on blob download replaced with `except AzureError`.
`GeneratorResult.sources` changed to `list[int]`; formatting to `"Source 1"` belongs in
the presentation layer, not the domain model.

**Takeaway:** Write the ownership walkthrough into the Definition of Done and run it before
every push, not just once after the first smoke test.