# ADR-006: Split Shared Contracts from Context-Local Result Types

Status: Accepted
Date: 2025-03-21
Deciders: Kevin Sokoll

## Context

An initial draft of `BOUNDED_CONTEXTS.md` placed all Pydantic
schemas (`CustomerQuery`, `IntentClassification`,
`GeneratorResult`, `QualityResult`, `PipelineResult`) plus four
exception classes in a single `core/models.py`. At nine classes
in one file, this was already approaching God Module territory
and contradicted the bounded context philosophy from ADR-001:
if each context owns its boundary, it should also own its
output contract.

The practical pain would have been: a change to
`IntentClassification` (e.g. adding a confidence field) would
have forced an edit to a shared module that all four contexts
depend on. Notionally, this could affect the import graph of
every context, even though the actual change only mattered for
classification.

## Decision

Split into three locations:

- `core/models.py` retains only schemas that cross context
  boundaries: `CustomerQuery` (pipeline entry contract) and
  `PipelineResult` (pipeline exit contract).
- `core/exceptions.py` holds all four domain exception
  classes.
- Context-local result types live in their own context
  module: `IntentClassification` in
  `classification/models.py`, `GeneratorResult` in
  `generation/models.py`, `QualityResult` in
  `quality_assurance/models.py`.

## Rationale

- A context's result type is part of that context's boundary
  definition. `IntentClassification` is the output contract
  of the Classification context. It belongs there, not in a
  shared module that all contexts depend on. Moving it into
  `classification/models.py` means changes to classification
  output only touch the classification context.
- Exceptions live in `core/exceptions.py` rather than their
  originating contexts because `pipeline.py` is the single
  consumer of all of them. If exceptions lived in their
  contexts, `pipeline.py` would need to import from all four
  contexts just to reference exception types. This creates
  a dependency on the context modules with no business
  logic justification. `core/` is the correct neutral
  location.
- The stub-first approach matters: context-local
  `models.py` files are created in the skeleton phase before
  `core/models.py` is written. This allows `PipelineResult`
  to import `IntentClassification`, `GeneratorResult`, and
  `QualityResult` immediately without circular imports or
  `Any`-typed placeholders.
- This is the natural evolution of ADR-001: if bounded
  contexts own their boundaries, they own their result
  types too.

## Alternatives Considered

| Dimension | All in core/models.py | Split (chosen) | All in context modules |
|---|---|---|---|
| File grows unbounded | Yes | No | No |
| Context-local changes touch core | Yes | No | No |
| pipeline.py imports from contexts | Only for results | Only for results | For results AND exceptions |
| Single source of truth for cross-context types | Yes | Yes | No |
| Risk of God Module | High | Low | Low |

The first alternative (everything in `core/models.py`) is
simpler to navigate initially but grows unbounded as contexts
are added, and any change to a context's output type forces a
touch on the shared module. The third alternative (everything
in context modules including exceptions) was rejected because
exceptions in their contexts would force `pipeline.py` to
import from all four contexts for exception handling alone,
creating dependencies that have no business logic
justification. The chosen split keeps cross-context contracts
in `core/` and context-local types in the contexts that own
them.

## Consequences

Positive:
- Changes to `IntentClassification` only touch
  `classification/`
- `core/models.py` stays small and focused on real
  cross-context contracts
- Each context's `models.py` documents its output contract
  in one place

Negative:
- A new contributor must learn the rule "shared types in
  core, context-local types in the context"; it is not
  obvious from a directory listing alone
- Cross-references between contexts (e.g. `PipelineResult`
  needing to import `IntentClassification`) require
  importing across module boundaries, which is fine for
  `pipeline.py` but would be an architectural smell
  anywhere else

Neutral:
- The exception location (`core/exceptions.py`) is a
  pragmatic choice based on `pipeline.py` being the single
  consumer; if a future change made exceptions
  context-specific in usage, they could move
- The split creates an asymmetry: result types are
  context-local, exceptions are shared. This asymmetry is
  documented here so future readers know it is intentional
