# ADR-005: Hallucination Check Merged into Judge Prompt

Status: Accepted
Date: 2025-03-18
Deciders: Kevin Sokoll

## Context

The original `quality_check.py` made three separate LLM calls per
request: one for coherence and hallucination checking via
`_check_hallucination`, one for answer classification via
`AnswerJudge`, and one for the human-in-the-loop (HITL) decision.
The hallucination check was a standalone LLM call with its own
prompt and JSON parsing. This meant three round-trips to the API
for every customer query processed by the pipeline.

The cost and latency implications were measurable. For a customer
support system where response time is user-facing, three
sequential LLM calls per query meant the quality assurance phase
alone added several hundred milliseconds of latency on top of
generation. The cost per query was also tripled for the QA phase.

## Decision

Remove `_check_hallucination` as a standalone LLM call. Merge
fact-checking into the `AnswerJudge` prompt as Step 1 of a
three-step sequential evaluation:

1. Fact check: does the answer contain claims not supported by
   the context? Returns `hallucination_detected: bool` and a
   list of unsupported claims.
2. Classification:
   `no_match` / `mediocre_match` / `good_match`.
3. HITL decision: escalation triggers, with
   `hallucination_detected: true` always triggering escalation.

Technical checks (coherence, length) remain as pure Python
functions in `checker.py` with no LLM calls.

## Rationale

- One LLM call with a structured three-step prompt produces
  evaluation quality equivalent to three separate calls, at
  one-third the latency and cost per request. For a customer
  support system where response time is user-facing, this
  matters.
- The fact check and the answer classification are not
  independent. A hallucinated answer is by definition a poor
  match. Evaluating them in the same prompt context allows
  the model to reason about them jointly rather than in
  isolation. Three separate calls would lose this joint
  context.
- Pure technical checks (length, coherence) do not need an
  LLM. They are deterministic, instantaneous, and freely
  unit-testable. Keeping them in `checker.py` as pure
  functions preserves that property. Only the semantic
  evaluation (factual grounding, answer quality, escalation
  judgement) warrants an LLM call.
- Escalation logic in the prompt means policy changes (e.g.
  adding a new escalation trigger) require only a prompt
  update and a re-evaluation of test cases. No code
  deployment needed.

## Alternatives Considered

Three alternatives were considered. The first was keeping three
separate LLM calls. This offers maximum modularity per call but
costs three times the latency and money, and each call loses
context from the others: the hallucination checker does not know
the classification, and the classifier does not know about
detected hallucinations. The second was removing hallucination
checking entirely. This reduces cost further but hallucination
detection is a core quality signal for a RAG system, and
removing it would lower the reliability of the HITL decision.
The third was keeping hallucination checking as Python rules
based on string matching against the context. This is too brittle
for the natural-language case where the same fact can be phrased
many ways. The merged-prompt approach captures the cost benefit
of fewer calls while keeping the semantic flexibility of LLM
evaluation.

## Consequences

Positive:
- Quality assurance latency dropped to roughly one-third of the
  original per query
- Cost per QA evaluation dropped by the same factor
- Joint reasoning across fact check, classification, and HITL
  produces more coherent evaluations than three isolated calls

Negative:
- The merged prompt is longer and more complex than each of the
  three original prompts. Editing it requires care to not break
  any of the three steps.
- A failure in the JSON parsing of the merged response affects
  all three evaluation steps simultaneously, rather than just
  one
- If the model hallucinates the structured output format, the
  entire QA result is unusable rather than two of three steps
  being usable

Neutral:
- Pure Python coherence and length checks remain in
  `checker.py` and do not interact with the merged LLM prompt
- The merged prompt structure (three labelled steps) is
  testable via dummy LLM clients that return canned
  three-step responses
