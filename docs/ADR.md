ADR-001: DDD Refactor with Bounded Contexts

Context: The original customer-support-ai codebase had ~500-700 lines of logic across 12 flat files in src/. All components (classifier, retriever, generator, quality checker) shared the same namespace, had no explicit contracts between stages, and returned raw dicts across boundaries. Adding a new provider or swapping a component required touching multiple unrelated files.

Decision: Restructure the project around four bounded contexts: Classification, Retrieval, Generation, Quality Assurance. Each context owns its module folder, its local result type, and its own tests. All cross-context communication is routed through pipeline.py.

Reasoning:
* Each context has a distinct responsibility, lifecycle, and dependency profile. Classification is a pure input-to-label transformation. Retrieval depends on an embedding model. Generation depends on context documents. Quality Assurance depends on the full answer. These are not the same concern.
* Boundary rules enforced by convention ("no context imports from another context directly") make the architecture testable: each context can be unit-tested in isolation with dummy clients and synthetic data.
* The flat file structure was approaching Zone of Pain (Architecture Rule #10): adding a feature required touching the classifier, the pipeline, the quality checker, and the models file simultaneously. Bounded contexts localise change.
* Portfolio-explicitly: the structure demonstrates architectural reasoning, not just working code. A recruiter or technical interviewer reading the repo can infer the design intent from the folder structure alone.

Alternatives considered:
* Keep flat structure, improve naming: reduces friction but does not solve coupling. The same change still touches multiple files.
* Service-based split (separate FastAPI services per context): correct for a production multi-team system, but over-engineered for a single-developer portfolio project. Adds network latency, distributed tracing complexity, and deployment overhead with no benefit at this scale.

---

ADR-002: Protocol-based LLM and Embedding client abstraction

Context: The original code instantiated OpenAI() directly inside four separate classes (IntentClassifier, ResponseGenerator, QualityChecker, AnswerJudge). Provider switching required editing each class individually. The if settings.llm_provider == "openai" branching was copy-pasted across all four files. There was no shared contract between the domain logic and the AI infrastructure.

Decision: Define two runtime_checkable Protocols in services/client.py: LLMClient with complete(request: CompletionRequest) -> CompletionResult, and EmbeddingClient with embed(texts: list[str]) -> list[list[float]]. All bounded contexts receive their client via constructor injection. No context imports a concrete client directly.

Reasoning:
* Constructor injection makes every context unit-testable without a real API key. DummyLLMClient and DummyEmbeddingClient are sufficient for all unit and integration tests.
* The Protocol approach (structural subtyping) is idiomatic Python. New providers (Anthropic, local Ollama, Azure OpenAI) are addable without modifying any bounded context — only services/client.py changes.
* Two separate Protocols, not one: the signatures are fundamentally incompatible (complete takes a prompt pair and returns a string, embed takes a list of texts and returns a matrix). Collapsing them into one Protocol would require either empty method stubs or a forced method that serves neither consumer well. Consumers are also different: LLMClient is used by Classification, Generation, and Quality Assurance; EmbeddingClient is used exclusively by Retrieval.
* CompletionRequest as a Pydantic model carries all call-site-specific parameters (temperature, response_format, max_tokens). This avoids **kwargs catch-alls that would break mypy strict mode and hide parameter drift between components.

Alternatives considered:
* Abstract base classes (ABC): heavier than needed. Python Protocols achieve the same structural contract without requiring explicit inheritance. ABC would force every implementation to import from services/, creating an upward dependency.
* Single LLMClient protocol with both complete() and embed(): forces all LLM clients to implement an embed() method they do not use, and all embedding clients to implement complete(). Violates Interface Segregation.
* Direct OpenAI import with provider flag: the status quo. Untestable without credentials, requires multi-file changes to swap providers.

---

ADR-003: RetrieverProtocol with FAISSRetriever and BlobRetriever

Context: The original project had two retriever implementations (KnowledgeRetriever reading from local disk, BlobKnowledgeRetriever reading from Azure Blob Storage) with no shared interface. The pipeline hardcoded BlobKnowledgeRetriever, making local development without Azure credentials impossible. Both implementations duplicated the same retrieve() signature without any contract.

Decision: Define RetrieverProtocol in retrieval/retriever.py with a single method retrieve(query: str, k: int) -> list[str]. Provide FAISSRetriever (local disk, used in development and tests) and BlobRetriever (Azure Blob, used in production) as implementations. The pipeline depends on RetrieverProtocol only. The concrete implementation is chosen at startup based on settings.enable_blob_retrieval.

Reasoning:
* With RetrieverProtocol in place, the pipeline never needs to know which retriever is active. Switching from local to production requires only an environment variable change, not a code change.
* FAISSRetriever as the default for development means all unit and integration tests run without Azure credentials. This is a prerequisite for hermetic testing (ML Engineering Rule: hermetic tests use synthetic data and local dependencies).
* BlobRetriever builds a transient in-memory FAISS index on startup from the blob contents. This avoids the need to manage a separately deployed vector store service, while still allowing the knowledge base to live in cloud storage.

Alternatives considered:
* Single retriever with an internal if/else on settings.enable_blob_retrieval: eliminates the Protocol but couples the retriever to the config. Makes unit testing harder (the blob branch is unreachable without credentials). Violates the open-closed principle.
* Pinecone, Weaviate, or another managed vector store: valid for production at scale, but introduces a paid external dependency and adds infrastructure complexity that is not justified for this project size.

---

ADR-004: Direct faiss-cpu over LangChain FAISS wrapper

Context: The original retriever used langchain_community.vectorstores.FAISS, which internally manages a faiss.IndexFlatL2, a docstore for text mapping, and its own Embeddings interface. Integrating our EmbeddingClient Protocol with LangChain would have required an adapter class to translate between the two interfaces. LangChain also brings langchain-core, langchain-community, and their transitive dependencies into the Docker image.

Decision: Replace langchain_community.vectorstores.FAISS with direct faiss-cpu calls. Manage the text-to-index mapping ourselves via a parallel list[str] serialized as texts.json alongside the index.faiss file. Remove LangChain from the retrieval dependency chain entirely.

Reasoning:
* What LangChain's FAISS wrapper actually does: call embed(), build faiss.IndexFlatL2, call faiss.search(), wrap results in Document objects. This is four lines of logic behind a dependency that pulls in ~15 packages. Replacing it with direct faiss-cpu calls makes the entire retrieval pipeline visible and transparent.
* The text-to-index mapping problem (FAISS returns integer indices, not texts) is trivially solved with a parallel list. LangChain hides this behind its docstore abstraction, which implies complexity that does not exist.
* Removing LangChain reduces the API Docker image size measurably and eliminates a class of dependency conflicts (LangChain releases frequently and breaks pinned versions).
* Direct faiss-cpu gives us full control over the EmbeddingClient injection. A LangChain adapter would have been glue code written purely to satisfy LangChain's interface, not to solve a domain problem. This is accidental complexity by definition (Architecture Rule #2: guide technology choices, do not write adapter code to accommodate a dependency's interface).

Alternatives considered:
* LangChain with EmbeddingClient adapter: works, but writes glue code for the wrong reason. The adapter exists because LangChain demands it, not because the domain requires it.
* LangChain retained as-is, Protocol not injected: violates the refactor goal. The retriever becomes untestable without an OpenAI key.
* Alternative vector stores (Chroma, Qdrant in-memory): add another dependency for a problem faiss-cpu already solves. No benefit at this scale.

---

ADR-005: Hallucination check merged into Judge prompt

Context: The original quality_check.py made three separate LLM calls per request: one for coherence/hallucination checking (_check_hallucination), one for answer classification (AnswerJudge), and one for HITL decision. The hallucination check was a standalone LLM call with its own prompt and JSON parsing. This meant three round-trips to the API for every customer query processed by the pipeline.

Decision: Remove _check_hallucination as a standalone LLM call. Merge fact-checking into the AnswerJudge prompt as Step 1 of a three-step sequential evaluation: (1) Fact check: does the answer contain claims not supported by the context? Returns hallucination_detected: bool and a list of unsupported claims. (2) Classification: no_match / mediocre_match / good_match. (3) HITL decision: escalation triggers, with hallucination_detected: true always triggering escalation. Technical checks (coherence, length) remain as pure Python functions in checker.py with no LLM calls.

Reasoning:
* One LLM call with a structured three-step prompt produces equivalent evaluation quality to three separate calls, at one-third the latency and cost per request. For a customer support system where response time is user-facing, this matters.
* The fact check and the answer classification are not independent: a hallucinated answer is by definition a poor match. Evaluating them in the same prompt context allows the model to reason about them jointly rather than in isolation.
* Pure technical checks (length, coherence) do not need an LLM. They are deterministic, instantaneous, and freely unit-testable. Keeping them in checker.py as pure functions preserves that property. Only the semantic evaluation (factual grounding, answer quality, escalation judgement) warrants an LLM call.
* Escalation logic in the prompt means policy changes (e.g. adding a new escalation trigger) require only a prompt update and a re-evaluation of test cases. No code deployment needed.

Alternatives considered:
* Keep three separate LLM calls: maximum modularity per call, but three times the latency and cost. Each call also loses context from the others (the hallucination checker does not know the classification, the classifier does not know about detected hallucinations).
* Remove hallucination checking entirely: reduces cost further, but hallucination detection is a core quality signal for a RAG system. Removing it would lower the reliability of the HITL decision.

---

ADR-006: Split shared contracts from context-local result types

Context: An initial draft of BOUNDED_CONTEXTS.md placed all Pydantic schemas (CustomerQuery, IntentClassification, GeneratorResult, QualityResult, PipelineResult) plus four exception classes in a single core/models.py. At nine classes in one file, this was already approaching God Module territory and contradicted the bounded context philosophy: if each context owns its boundary, it should also own its output contract.

Decision: Split into three locations. core/models.py retains only schemas that cross context boundaries: CustomerQuery (pipeline entry contract) and PipelineResult (pipeline exit contract). core/exceptions.py holds all four domain exception classes. Context-local result types live in their own context module: IntentClassification in classification/models.py, GeneratorResult in generation/models.py, QualityResult in quality_assurance/models.py.

Reasoning:
* A context's result type is part of that context's boundary definition. IntentClassification is the output contract of the Classification context. It belongs there, not in a shared module that all contexts depend on. Moving it into classification/models.py means changes to classification output only touch the classification context.
* Exceptions live in core/exceptions.py rather than their originating contexts because pipeline.py is the single consumer of all of them. If exceptions lived in their contexts, pipeline.py would need to import from all four contexts just to reference exception types. This creates a dependency on the context module with no business logic justification. core/ is the correct neutral location.
* Stub-first approach: context-local models.py files are created in the skeleton phase (Step 1) before core/models.py is written. This allows PipelineResult to import IntentClassification, GeneratorResult, and QualityResult immediately without circular imports or Any-typed placeholders.

Alternatives considered:
* All schemas in core/models.py: simpler to navigate initially, but grows unbounded as contexts are added. Any change to a context's output type forces a touch on the shared module, which notionally affects all other contexts.
* Result types in core/models.py, exceptions in context modules: the inverse. Exceptions in their contexts would force pipeline.py to import from all four contexts for exception handling alone. Rejected for the same coupling reason described above.