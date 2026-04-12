# ADR-002: Protocol-Based LLM and Embedding Client Abstraction

Status: Accepted
Date: 2025-03-03
Deciders: Kevin Sokoll

## Context

The original code instantiated `OpenAI()` directly inside four
separate classes: `IntentClassifier`, `ResponseGenerator`,
`QualityChecker`, and `AnswerJudge`. Provider switching required
editing each class individually. The
`if settings.llm_provider == "openai"` branching was copy-pasted
across all four files. There was no shared contract between the
domain logic and the AI infrastructure.

The consequences were practical: every test that touched any of
these classes needed a real OpenAI API key to instantiate, which
made hermetic unit testing impossible. Adding Anthropic support
would have meant four separate code edits with four chances to
get the branching wrong. The codebase had a hidden coupling to
one specific provider library.

## Decision

Define two `runtime_checkable` Protocols in `services/client.py`:

- `LLMClient` with
  `complete(request: CompletionRequest) -> CompletionResult`
- `EmbeddingClient` with
  `embed(texts: list[str]) -> list[list[float]]`

All bounded contexts receive their client via constructor
injection. No context imports a concrete client directly. The
concrete implementation is selected at composition root, not
inside the contexts themselves.

## Rationale

- Constructor injection makes every context unit-testable
  without a real API key. `DummyLLMClient` and
  `DummyEmbeddingClient` are sufficient for all unit and
  integration tests.
- The Protocol approach (structural subtyping) is idiomatic
  Python. New providers (Anthropic, local Ollama, Azure
  OpenAI) are addable without modifying any bounded context;
  only `services/client.py` changes.
- Two separate Protocols, not one: the signatures are
  fundamentally incompatible. `complete` takes a prompt pair
  and returns a string, `embed` takes a list of texts and
  returns a matrix. Collapsing them into one Protocol would
  require either empty method stubs or a forced method that
  serves neither consumer well. This is the Interface
  Segregation Principle in practice.
- Consumers are also different. `LLMClient` is used by
  Classification, Generation, and Quality Assurance.
  `EmbeddingClient` is used exclusively by Retrieval. The
  separation matches actual usage.
- `CompletionRequest` as a Pydantic model carries all
  call-site-specific parameters (temperature, response_format,
  max_tokens). This avoids `**kwargs` catch-alls that would
  break mypy strict mode and hide parameter drift between
  components.
- Direct application of `architecture.md` Rule #2: "Guide
  technology choices, do not specify them. Say 'use a
  Protocol-based client interface' not 'use OpenAI'."

## Alternatives Considered

| Dimension | Direct OpenAI import | Single ABC | Two Protocols |
|---|---|---|---|
| Provider switching cost | Edit 4 files | Edit 4 implementations | Add 1 file |
| Test without API key | Impossible | Possible | Possible |
| Interface Segregation | Violated | Violated | Honored |
| mypy strict compliance | OK | OK | OK |
| Idiomatic Python | No | Acceptable | Yes |
| Inheritance forced | No | Yes | No |

The two-Protocol approach wins on every dimension. Abstract base
classes (ABC) were rejected because they are heavier than needed:
Python Protocols achieve the same structural contract without
requiring explicit inheritance, and ABC would force every
implementation to import from `services/`, creating an upward
dependency that the Protocol approach avoids. A single combined
LLM-and-embedding Protocol was rejected because it forces all LLM
clients to implement an `embed()` method they do not use, and
all embedding clients to implement `complete()`. This is a
textbook Interface Segregation violation.

## Consequences

Positive:
- All four bounded contexts can be unit tested without API
  credentials
- Adding a new provider (e.g. Anthropic) is one new file in
  `services/`, no changes to any context
- mypy strict mode catches parameter drift between components
  via the typed `CompletionRequest`

Negative:
- The Protocol must be kept narrow. Adding methods that only
  one provider supports creates pressure to widen it.
- Provider-specific features (like Anthropic's prompt
  caching) have to be modeled inside the concrete client, not
  exposed via the Protocol

Neutral:
- The `CompletionRequest` and `CompletionResult` dataclasses
  become the contract between contexts and providers; their
  shape is the real interface
- Composition root (where concrete clients are wired into
  contexts) is one place in `pipeline.py` or its caller
