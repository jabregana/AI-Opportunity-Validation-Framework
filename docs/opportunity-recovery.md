---
type: opportunity
dimension: recovery
stage: 1
status: WEDGE-CANDIDATE
date: 2026-06-07
---

# Stage 1 opportunity scan: agent recovery behavior

This is the Stage 1 landscape scan for the **recovery** dimension, one of the four scaffolded dimensions in [`six-dimensions-architecture.md`](six-dimensions-architecture.md). Goal: find a wedge worth taking through Stages 2-4.

Recovery behavior covers what an agent does when something goes wrong: tool errors, model refusals, validation failures, timeouts, partial results, output-format mismatches, repeated identical outputs (loops), and budget exhaustion. Most agent demos perform well on the golden path and badly on these failure modes. Existing tools partially address it; nothing measures it as a statistical system.

## What the incumbents do today

| Tool / framework | Recovery primitives shipped | Gaps |
|---|---|---|
| **LangChain** | `RunnableRetry` with exponential backoff; `with_fallbacks` for chain-level fallback chains; error-catching in Tool wrappers | No structured failure taxonomy. Retries are opaque (no record of what was retried or why). No statistical evaluation of recovery policies. |
| **LangGraph** | Conditional edges can route on errors; `interrupt` for human-in-loop on failure | Recovery is hand-coded per graph. No reusable recovery policies. No benchmarks. |
| **AutoGen** | Multi-agent escalation (failed agent hands to supervisor); turn-limit guards | Escalation is policy-as-prompt, not policy-as-code. No way to A/B test recovery strategies. |
| **Anthropic SDK / OpenAI SDK** | `tool_choice` allows hinting (`required`, `auto`, `none`); structured-output schemas catch format violations at the API layer | No retry policy. No fallback chain. App developer reinvents. |
| **Inspect AI** | Evaluation framework; can score whether an agent recovered from injected failures | Evaluation only; does not provide reusable recovery primitives. |
| **Pydantic Evals** | Validator failures surface in eval results | Recovery is not in scope; only detection. |
| **Arize Phoenix / LangSmith / Langfuse** | Trace failed runs; group by error type | Observability only. No policy primitives, no statistical comparison of recovery strategies. |
| **OpenTelemetry semantic conventions for genai** | Records tool errors, retries, fallbacks in spans | Standard for recording, not policy. No comparison framework. |
| **Guardrails AI / NeMo Guardrails** | Structured-output validators with re-ask loops | Re-ask is the only recovery primitive; no benchmark for whether re-ask vs fallback-model vs ask-user is best in a given context. |

## What is missing

A statistical evaluation harness for recovery policies that can answer questions like:

- **"For this task class, does retry beat fallback-to-larger-model on completion rate, given equal cost budget?"**
- **"At what point in the retry sequence does an additional attempt no longer move the success rate?"**
- **"Which failure-kind taxonomy actually predicts recovery success?"** (Most tools today treat all errors as one bucket.)
- **"When the model refuses, is ask-user better than rephrase-and-retry?"**
- **"How does the right recovery policy change across model sizes?"** (A 3B local model has very different failure modes than gpt-4o.)

None of the incumbents above can A/B test recovery policies under controlled failure injection across a model ladder with statistical confidence. They either lack the policy primitive (most observability tools), the eval framework (most agent frameworks), or the failure taxonomy (almost everyone).

## Three candidate wedges

### Wedge A: Recovery-policy benchmark suite (controlled failure injection + statistical comparison)

A synthetic workload that injects controlled failures into agent tasks at known points, plus a `RecoveryVariant` family that can be A/B tested against each other under the existing harness (paired bootstrap, CUPED, LORD++ FDR, CI gates).

- **Pros**: Maps cleanly onto the existing framework. The `RecoveryVariant` ABC already exists (`runner/dimensions/recovery/base.py`). The `Failure` and `RecoveryAction` dataclasses already exist. Synthetic failure injection is cheap to build. The wedge is "the first apples-to-apples benchmark for recovery policies across the failure-kind taxonomy."
- **Cons**: Synthetic failures might not mirror real failure distributions. Stage 3 needs real failure traces to validate.
- **Incumbent overlap**: None directly. Inspect AI evaluates recovery but does not provide reusable policy primitives. LangChain ships retry primitives but does not benchmark them.

### Wedge B: Failure-taxonomy refinement

Most retry policies today treat all errors as one bucket. A refined taxonomy (transient-network vs validation-mismatch vs model-refusal vs out-of-budget vs ambiguous-tool-result) might let policies route more precisely. Build the taxonomy + show it predicts recovery success better than "any-error" buckets.

- **Pros**: Genuinely novel angle. Useful even if the policy comparison work (Wedge A) gets done by someone else first.
- **Cons**: Taxonomy work tends to be subjective. Hard to defend "this is the right taxonomy" without a strong empirical claim.
- **Incumbent overlap**: Some overlap with structured-output validators (Guardrails, Pydantic Evals) which implicitly carry small taxonomies. None of those have done the predictive-power claim.

### Wedge C: Recovery-policy auto-tuning

Given a task class and a failure distribution, automatically select the recovery policy that maximizes completion-rate-per-dollar. Either an offline-trained selector or an online bandit.

- **Pros**: The "product" framing. If it works, it sells.
- **Cons**: Massive scope. Needs Wedge A + Wedge B as prerequisites. Online bandit requires production telemetry. Not a credible first wedge.
- **Incumbent overlap**: Some routing tools (Martian, RouteLLM) do model-level routing; none do recovery-policy-level routing.

## Pick: Wedge A (benchmark suite)

For three reasons:

1. **It is the prerequisite for B and C.** Both refined taxonomy and auto-tuning need a benchmark to validate against. A is the foundation.
2. **It matches the framework's current capability.** The `RecoveryVariant` ABC ships in `runner/dimensions/recovery/`. The statistical harness already handles the comparison shape (paired outcomes, FDR control, CIs). Adding a synthetic failure-injection workload is a few hundred lines.
3. **The incumbent gap is on the record.** None of LangChain, LangGraph, AutoGen, Inspect AI, Phoenix, LangSmith, or Langfuse offer apples-to-apples recovery-policy comparison. Each ships either the primitive or the eval, never both with statistical control.

This mirrors the wedge-pick logic from [`opportunity.md`](opportunity.md) (the schema-alignment proxy): pick the wedge where the incumbent's gap is structural, not a roadmap item.

## Out-of-scope for Stage 1

These are real concerns but not part of the wedge pick:

- **Real failure traces** (Stage 3 problem)
- **Production telemetry integration** (Wedge C concern, deferred)
- **Cost modeling** (worth doing in Stage 2 but not load-bearing on the wedge pick)
- **Refusal-detection ML** (separate problem; recovery is what to do once refusal is detected)

## Stage 2 plan (sketch, not committed)

If Wedge A holds up, Stage 2 looks like:

**Day 1**: Verify the incumbent state. Read LangChain's `RunnableRetry` source. Read LangGraph's error-routing examples. Confirm Inspect AI's evaluation primitives.

**Day 2**: Build the synthetic failure-injection workload. Likely a task-completion workload (e.g., "use these N tools to answer this question") with deterministic failure injection at known points (drop call M, return malformed JSON on call K, refuse on call L). Modeled on `fixtures/workloads/w_graph_churn.py`'s deterministic-with-seed pattern.

**Day 3**: Build three pilot recovery variants:
- `b-abort-on-failure` (already in `runner/dimensions/recovery/b_noop.py`)
- `recovery-v0.1.0-retry-with-backoff` (exponential, max 3 attempts)
- `recovery-v0.1.1-fallback-chain` (smaller model on failure, then larger, then abort)

**Day 4**: Wire up the runner with UC gates:
- UC-REC-1: task completion rate >= baseline + threshold
- UC-REC-2: cost-per-successful-completion <= baseline * 1.5
- UC-REC-3: p99 task latency <= baseline + threshold
- UC-REC-4: no recovery loop exceeds the configured max-attempts

**Day 5**: Run the first benchmark + write the first finding doc.

If Day 5 passes, Stage 3 hooks the variants into a real agent (a LangGraph workflow or a Claude tool-use loop) and runs on real failure traces from a corpus the user already has access to.

## Pointers

- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Existing scaffolding: `runner/dimensions/recovery/{base.py, b_noop.py, __init__.py}`
- Framework narrative: [`../FRAMEWORK.md`](../FRAMEWORK.md)
- Precedent for this scan's shape: [`opportunity.md`](opportunity.md) (proxy wedge), [`opportunity-graph-gc.md`](opportunity-graph-gc.md) (graph-GC wedge)
