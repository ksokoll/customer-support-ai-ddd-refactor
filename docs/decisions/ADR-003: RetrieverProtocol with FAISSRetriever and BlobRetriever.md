# ADR-003: RetrieverProtocol with FAISSRetriever and BlobRetriever

Status: Accepted
Date: 2025-03-10
Deciders: Kevin Sokoll

## Context

The original project had two retriever implementations,
`KnowledgeRetriever` reading from local disk and
`BlobKnowledgeRetriever` reading from Azure Blob Storage, with
no shared interface between them. The pipeline hardcoded
`BlobKnowledgeRetriever`, which made local development without
Azure credentials impossible. Both implementations duplicated
the same `retrieve()` signature without any contract enforcing
that they remain compatible.

The practical consequence: a developer wanting to run the
pipeline locally had to either provision Azure credentials or
manually swap the retriever in the pipeline source. There was
no clean way to switch between the two without code changes,
and no test could exercise the production blob path without
real Azure access.

## Decision

Define `RetrieverProtocol` in `retrieval/retriever.py` with a
single method
`retrieve(query: str, k: int) -> list[str]`. Provide
`FAISSRetriever` (local disk, used in development and tests)
and `BlobRetriever` (Azure Blob, used in production) as
implementations. The pipeline depends on `RetrieverProtocol`
only. The concrete implementation is chosen at startup based
on `settings.enable_blob_retrieval`.

## Rationale

- With `RetrieverProtocol` in place, the pipeline never needs
  to know which retriever is active. Switching from local to
  production requires only an environment variable change,
  not a code change.
- `FAISSRetriever` as the default for development means all
  unit and integration tests run without Azure credentials.
  This is a prerequisite for hermetic testing
  (`ml_engineering.md`: hermetic tests use synthetic data
  and local dependencies).
- `BlobRetriever` builds a transient in-memory FAISS index
  on startup from the blob contents. This avoids the need
  to manage a separately deployed vector store service,
  while still allowing the knowledge base to live in cloud
  storage.
- This is the same Protocol-based pattern as ADR-002 applied
  to retrieval: separate the interface from the
  implementation, inject at composition root, test with a
  dummy.

## Alternatives Considered

Two alternatives were considered. The first was a single
retriever class with an internal `if/else` on
`settings.enable_blob_retrieval`. This eliminates the Protocol
but couples the retriever to the config object. It also makes
unit testing harder because the blob branch is unreachable
without credentials, and it violates the open-closed principle:
adding a third backend would mean modifying the existing class
instead of adding a new one. The second was using a managed
vector store like Pinecone or Weaviate. This is valid for
production at scale, but it introduces a paid external
dependency and adds infrastructure complexity that is not
justified for this project size. FAISS-on-disk for local plus
FAISS-from-blob for production covers both environments
without external services.

## Consequences

Positive:
- Local development requires no Azure credentials
- Unit tests use `FAISSRetriever` and run hermetically
- A third backend (e.g. Pinecone) could be added as one new
  file implementing the Protocol, no changes to the pipeline

Negative:
- The transient in-memory index in `BlobRetriever` rebuilds
  on every startup, which adds startup latency proportional
  to the knowledge base size
- The retriever interface returns plain strings, not
  documents with metadata. Adding metadata later would
  require widening the Protocol.

Neutral:
- The Protocol is narrow (one method) and easy to extend if
  future requirements demand it
- Selection between `FAISSRetriever` and `BlobRetriever`
  happens at composition root, not inside any context
