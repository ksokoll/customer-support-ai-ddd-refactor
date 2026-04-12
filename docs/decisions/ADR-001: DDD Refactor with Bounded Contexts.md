# ADR-001: DDD Refactor with Bounded Contexts

Status: Accepted
Date: 2025-03-03
Deciders: Kevin Sokoll

## Context

The original `customer-support-ai` codebase had approximately 500
to 700 lines of logic spread across 12 flat files in `src/`. All
components (classifier, retriever, generator, quality checker)
shared the same namespace, had no explicit contracts between
stages, and returned raw dicts across boundaries.

The pain became concrete when adding new functionality. Adding a
provider or swapping a component required touching multiple
unrelated files: the classifier, the pipeline, the quality
checker, and the models file all had to be updated for what was
nominally a single change. The dict-based return values meant
that a malformed result from one component would propagate
through several stages before raising an attribute error far from
the source. The codebase had reached the Zone of Pain described
in `architecture.md` Rule #10.

## Decision

Restructure the project around four bounded contexts:
Classification, Retrieval, Generation, Quality Assurance. Each
context owns its module folder, its local result type, and its
own tests. All cross-context communication is routed through
`pipeline.py`. No context imports directly from another context.

## Rationale

- Each context has a distinct responsibility, lifecycle, and
  dependency profile. Classification is a pure input-to-label
  transformation. Retrieval depends on an embedding model.
  Generation depends on context documents. Quality Assurance
  depends on the full answer. These are not the same concern
  and they should not share a namespace.
- Boundary rules enforced by convention ("no context imports
  from another context directly") make the architecture
  testable. Each context can be unit-tested in isolation with
  dummy clients and synthetic data, without spinning up the
  whole pipeline.
- The flat file structure was approaching the Zone of Pain
  described in `architecture.md` Rule #10. Bounded contexts
  localise change: a modification to the classifier touches
  only the classification context, not the pipeline or the
  models file.
- The folder structure communicates design intent without
  separate documentation. A reader can infer the architecture
  from the directory tree alone.

## Alternatives Considered

| Dimension | Flat structure | Bounded contexts | Microservices |
|---|---|---|---|
| Cohesion of related code | Low | High | High |
| Cost of adding a context | High | Low | Very low |
| Test isolation | Poor | Good | Excellent |
| Deployment complexity | Low | Low | High |
| Network latency | None | None | High |
| Right size for | Hobby/PoC | Single team, single repo | Multi-team production |

Bounded contexts capture most of the cohesion and test isolation
benefits of microservices without paying their deployment and
operational cost. Microservices were rejected as
over-engineered for a single-developer portfolio project: they
would add network latency, distributed tracing complexity, and
deployment overhead with no benefit at this scale. The flat
structure was rejected because it does not solve the coupling
problem that motivated the refactor in the first place.

## Consequences

Positive:
- Each context can be unit tested in isolation with dummy
  clients and synthetic data
- Adding a new context (e.g. summarization) requires creating
  a new folder, not modifying existing ones
- Folder structure communicates design intent without separate
  documentation
- Pull requests touching multiple contexts now signal a
  potential architectural smell that deserves review

Negative:
- `pipeline.py` becomes the single cross-context dependency,
  which concentrates orchestration knowledge in one place.
  Future refactor candidate.
- New developers must learn the context boundaries before
  contributing
- Import paths become deeper (e.g.
  `from app.classification.classifier import IntentClassifier`
  instead of `from classifier import IntentClassifier`)

Neutral:
- All future context-specific tests live under their context's
  test directory
- Each context owns its own result type (see ADR-006 for the
  split between shared contracts and context-local types)
