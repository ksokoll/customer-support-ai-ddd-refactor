# Template Coverage: AI_Project_Template_V3 vs. Refactor Priorities

## Directly Solved

**Weakness #1: No Protocols or Interfaces.**
`client.py` provides `ServiceClient` as a `runtime_checkable` Protocol with `complete()`. This is exactly what was missing. However, a `RetrieverProtocol` still needs to be added — the template does not include one.

**Weakness #2: Infrastructure instantiated inside the Domain.**
`processor.py` receives the client via constructor injection (`client: ServiceClient`). `pipeline.py` wires this together with `DummyClient` as the default. The pattern is clean and directly transferable.

**Weakness #6: Config bug.**
`config.py` uses clean Pydantic v2 `model_config` as a dict. No mixed v1/v2 syntax. All fields have defaults. Can be adopted directly.

**Weakness #7: DEBUG print statements in production code.**
The template uses `logging.getLogger(__name__)` throughout, with structured `extra` dicts. No print statements anywhere.

**Weakness #9: No pyproject.toml, no ADRs, no tests.**
`pyproject.toml` is complete with pytest markers (`unit`, `integration`, `e2e`), coverage config, Ruff, and Mypy. `ADR_TEMPLATE.md` is included. Ready to use as-is.

---

## Partially Solved

**Weakness #3: Two retrievers without a shared contract.**
The template includes `retriever.py`, but no `RetrieverProtocol`. Worse: `Processor.__init__()` instantiates the retriever directly (`self._retriever = Retriever()`). This is exactly the same problem as Weakness #2, repeated for the retriever. The template does not solve this — it reproduces it elsewhere. A `RetrieverProtocol` needs to be added, and the retriever must be injected into `Processor`.

**Weakness #8: Bare `except Exception`.**
`processor.py` catches `except Exception as exc` and chains with `raise RuntimeError(...) from exc`. This is better than a bare `except:`, but still not specific enough. For the RAG project, Azure- and OpenAI-specific exceptions need to be handled explicitly.

**Weakness #10: Global state.**
The template uses a lazy singleton in `main.py` via `get_pipeline()` with FastAPI `Depends`. The `rate_limiter` from the old project is not present in the template at all. If rate limiting is needed, it must be implemented cleanly as a FastAPI dependency.

---

## Not Solved — Requires Custom Work

**Weakness #4: No Bounded Contexts.**
The template defines `core/`, `services/`, and `prompts/`. That covers two to three contexts. The RAG project needs four: `classification/`, `retrieval/`, `generation/`, and `quality_assurance/`. `BOUNDED_CONTEXTS.md` describes the extension pattern, but the concrete structure must be designed specifically for this project. The template is a reference here, not a solution.

**Weakness #5: `answer_judge` and `quality_check` cut incorrectly.**
The template has no equivalent to a QualityAssurance context. This is project work that must be structured from scratch. Orientation from `BOUNDED_CONTEXTS.md`: a new context gets its own `schemas.py` and must only communicate with others through `pipeline.py`.

---

## Summary

| Weakness | Template Coverage |
|---|---|
| #1 Protocol / Interface | Direct: `ServiceClient`. Gap: no `RetrieverProtocol` |
| #2 Infrastructure in Domain | Directly solved |
| #3 No Retriever contract | Partial: retriever exists, but hardcoded inside Processor |
| #4 No Bounded Contexts | Template is a reference; structure must be built project-specifically |
| #5 QA cut incorrectly | Not in template; needs to be built from scratch |
| #6 Config bug | Directly solved |
| #7 Debug print statements | Directly solved |
| #8 Bare except | Partial: better than before, but not specific enough |
| #9 pyproject / ADRs / tests | Directly solved |
| #10 Global state | Partial: lazy singleton via Depends; rate limiter missing |

The template is a solid foundation for weaknesses #1, #2, #6, #7, and #9. The actual core of the refactor — the four Bounded Contexts and the QualityAssurance cut (#4 and #5) — is work that goes beyond what the template provides.