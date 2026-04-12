# ADR-004: Direct faiss-cpu over LangChain FAISS Wrapper

Status: Accepted
Date: 2025-03-15
Deciders: Kevin Sokoll

## Context

The original retriever used
`langchain_community.vectorstores.FAISS`, which internally
manages a `faiss.IndexFlatL2`, a docstore for text mapping, and
its own `Embeddings` interface. Integrating the `EmbeddingClient`
Protocol from ADR-002 with LangChain would have required an
adapter class to translate between the two interfaces. LangChain
also brings `langchain-core`, `langchain-community`, and their
transitive dependencies into the Docker image.

A look at what LangChain's FAISS wrapper actually does revealed
that the substantive logic was four lines: call `embed()`, build
`faiss.IndexFlatL2`, call `faiss.search()`, wrap results in
`Document` objects. The rest was abstraction overhead. The
adapter that would have connected `EmbeddingClient` to LangChain
existed solely to satisfy LangChain's interface, not to solve
any domain problem.

## Decision

Replace `langchain_community.vectorstores.FAISS` with direct
`faiss-cpu` calls. Manage the text-to-index mapping manually via
a parallel `list[str]` serialized as `texts.json` alongside the
`index.faiss` file. Remove LangChain from the retrieval
dependency chain entirely.

## Rationale

- What LangChain's FAISS wrapper does, expressed directly, is
  four lines of logic. Replacing it with direct `faiss-cpu`
  calls makes the entire retrieval pipeline visible and
  transparent. There is no abstraction layer to debug.
- The text-to-index mapping problem (FAISS returns integer
  indices, not texts) is trivially solved with a parallel
  list. LangChain hides this behind its docstore abstraction,
  which implies complexity that does not exist in the
  underlying problem.
- Removing LangChain reduces the API Docker image size
  measurably and eliminates a class of dependency conflicts.
  LangChain releases frequently and breaks pinned versions,
  which adds maintenance noise unrelated to the project's
  actual goals.
- Direct `faiss-cpu` gives full control over the
  `EmbeddingClient` injection. A LangChain adapter would have
  been glue code written purely to satisfy LangChain's
  interface, not to solve a domain problem. This is
  accidental complexity by definition
  (`architecture.md` Rule #2: guide technology choices, do
  not write adapter code to accommodate a dependency's
  interface).

## Alternatives Considered

| Dimension | LangChain wrapper | LangChain + adapter | Direct faiss-cpu | Managed vector store |
|---|---|---|---|---|
| Visible logic | Hidden | Hidden | Direct | Hidden |
| Embedding injection | Awkward | Adapter required | Native | Provider-specific |
| Dependency footprint | Heavy | Heavy | Minimal | External service |
| Cost at this scale | Free | Free | Free | Paid |
| Flexibility | LangChain decides | LangChain decides | Full | Provider decides |
| Risk of upstream breakage | High | High | Low | Medium |

Direct `faiss-cpu` wins on every dimension that matters at this
scale. Keeping LangChain with an adapter was rejected because the
adapter exists for the wrong reason: to satisfy a library's
interface, not to solve a domain problem. Keeping LangChain as-is
without the Protocol was rejected because it violates ADR-002
and makes the retriever untestable without an OpenAI key. A
managed vector store like Chroma or Qdrant adds a dependency for
a problem `faiss-cpu` already solves.

## Consequences

Positive:
- The entire retrieval pipeline is visible in one file with no
  hidden abstractions
- Docker image is significantly smaller without LangChain and
  its transitive dependencies
- No risk of upstream LangChain version changes breaking the
  retriever

Negative:
- The text-to-index mapping is now the project's
  responsibility. If the index and `texts.json` get out of
  sync, the retriever returns wrong text for the right
  embedding match.
- Some LangChain features (e.g. metadata filtering, hybrid
  search) would have to be reimplemented if needed later

Neutral:
- The `texts.json` serialization format is project-specific
  and not interoperable with other tools that expect
  LangChain or LlamaIndex formats
- Adding a new vector store would require implementing
  `RetrieverProtocol` from ADR-003, not adapting LangChain
