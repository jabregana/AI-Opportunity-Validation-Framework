---
type: stage-note
opportunity: agent recovery behavior
stage: 2
day: 1
date: 2026-06-07
---

# Stage 2 Day 1: incumbent verification

Goal: spot-check the two specific incumbents named in the framework's narrative ([`opportunity-recovery.md`](opportunity-recovery.md), Wedge A discussion) to confirm the opportunity is still open. Day 1 of the Stage 2 plan in [`opportunity-recovery.md`](opportunity-recovery.md) calls for verifying "LangChain `RunnableRetry` source, LangGraph error-routing examples." Did both via raw GitHub fetch.

## Verified: LangChain `RunnableRetry`

Source: `langchain-ai/langchain` repo, `libs/core/langchain_core/runnables/retry.py` (raw GitHub fetch, 2026-06-07).

What it ships:

| Field / behavior | What it does |
|---|---|
| `max_attempt_number: int = 3` | Hard cap on retries |
| `wait_exponential_jitter: bool = True` | Exponential backoff with jitter (default on) |
| `exponential_jitter_params: ExponentialJitterParams \| None` | Sub-knobs: `initial`, `max`, `exp_base`, `jitter` |
| `retry_exception_types: tuple[type[BaseException], ...] = (Exception,)` | Which exception classes trigger a retry |
| Internal: `"retry:attempt:{attempt}"` config tag | Callback tags per attempt (no aggregation, no outcome record) |

What it does NOT ship:

- **No failure-kind taxonomy.** The granularity is "which Python exception class did the underlying tool raise." That is not the same as classifying failures by semantic kind (tool_error vs model_refusal vs validation_failure vs timeout). The recommendation in the docstring is "retry on transient errors like 5xx and 429," but enforcing that is on the caller.
- **No fallback chain.** When retries exhaust, the final exception propagates (or returns as a failed result in batch mode). There is no "try smaller model, then larger, then ask user" primitive.
- **No per-retry outcome hooks.** Callbacks see attempt tags but there is no first-class API for recording "this retry attempt failed because X" in a structured form analyzable later.

## Verified: LangGraph `RetryPolicy`

Source: `langchain-ai/langgraph` repo, `libs/langgraph/langgraph/types.py` (raw GitHub fetch, 2026-06-07). Added in v0.2.24.

```python
class RetryPolicy(NamedTuple):
    """Configuration for retrying nodes."""
    initial_interval: float = 0.5
    backoff_factor: float = 2.0
    max_interval: float = 128.0
    max_attempts: int = 3
    jitter: bool = True
    retry_on: (
        type[Exception] | Sequence[type[Exception]] | Callable[[Exception], bool]
    ) = default_retry_on
```

What it ships:

- Per-node retry policy attachable via `retry_policy: RetryPolicy | Sequence[RetryPolicy] | None` in `StateGraph.add_node()` and `Pregel`.
- `retry_on` accepts an exception class, a sequence of classes, or a callable predicate. The callable variant is the most expressive: any Boolean function on the exception.
- Same time-scale knobs as LangChain (initial, backoff factor, max interval, max attempts, jitter).

What it does NOT ship:

- **No fallback chain primitive.** One policy per node. The `Sequence[RetryPolicy]` type is for *multiple* policies under different conditions on the same node, not a sequential fallback ladder.
- **No semantic failure-kind taxonomy.** The `retry_on` callable can implement one but it is not provided. Same gap as LangChain.
- **No per-retry outcome aggregation.** Tracing is via callbacks. No first-class evaluation surface for comparing two `RetryPolicy` instances on the same workload under statistical control.
- **No bandit / adaptive routing.** Policy is static at graph-build time. No mechanism to learn which `retry_on` predicate maximizes completion rate.

LangGraph's `retry_policy` shipped recently (v0.2.24) which suggests this slot is actively being filled. The filling is happening within the "exception-class-as-failure-kind" model that the opportunity scan already classified as too narrow.

## What is still open

Three things are clearly absent from both incumbents and would constitute the Stage 2 wedge:

1. **A semantic failure-kind taxonomy** that is separate from Python exception classes. A tool that returned an HTTP 503 and a tool that returned a malformed JSON and a model that refused to answer all raise different exception types in different SDKs. A semantic taxonomy unifies them so policies can be defined and compared at the semantic level.
2. **Sequential fallback chains as first-class objects.** "Retry, then fall back to smaller model, then fall back to ask-user, then abort" is a common need that neither LangChain nor LangGraph ships as a single primitive.
3. **A statistical evaluation surface** for comparing two recovery policies on the same workload (same model, same tools, same task distribution) under controlled failure injection. Neither incumbent provides this; their evaluation surface is either tracing (record what happened, no comparison) or single-run benchmarks.

The Stage 2 wedge (build a recovery-policy benchmark suite) addresses (3) directly. (1) and (2) are operationally needed by the benchmark to be meaningful, so the benchmark forces them into existence as a side effect.

## Not yet verified (deferred)

- Inspect AI's recovery evaluation primitives
- AutoGen / AG2 multi-agent escalation patterns
- Anthropic SDK / OpenAI SDK tool-use error-handling guidance (the SDK level, not framework level)
- Guardrails AI / NeMo Guardrails re-ask loops
- Langfuse / Arize Phoenix trace-aggregation of recovery outcomes

These were covered from training knowledge in the opportunity scan ([`opportunity-recovery.md`](opportunity-recovery.md)). Live verification deferred; would benefit from a deep-research workflow call if the Stage 2 work continues to a Stage 3 publication.

## Decision

The wedge is intact. Proceed to Day 2 (build the synthetic failure-injection workload). No edits needed to the opportunity scan's Wedge A pick.
