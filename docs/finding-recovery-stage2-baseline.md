---
type: finding
opportunity: agent recovery policy benchmark
stage: 2
status: PASS
date: 2026-06-07
artifact: runs/recovery_stage2_baseline/20260607T214125.json
---

# Recovery Stage 2 baseline: both pilot variants pass all four UC gates

First Stage 2 result on a non-memory dimension. The recovery dimension now has Stages 1 (wedge picked), 2 Day 1 (incumbents verified), 2 Day 2 (workload), and 2 Days 3-5 (pilot variants + runner + benchmark) complete.

**Headline**: on 500 synthetic scenarios with 30% failure rate, **both `retry-with-backoff` (+19.40pp completion) and `fallback-chain` (+26.60pp completion) pass all four UC-REC gates against the `b-abort-on-failure` baseline at lower cost per completion than baseline (0.90x ratio).** The framework's discipline carries cleanly from the two memory case studies to a third dimension.

## Setup

- **Workload**: `fixtures/workloads/w_failure_injection.py`, seed=42
  - 500 scenarios, 147 with injected failures (29.4%)
  - Failure distribution: 84 tool_error, 32 model_refusal, 18 timeout, 13 validation_failure
- **Variants**:
  - `b-abort-on-failure` (baseline): aborts on the first failure
  - `recovery-v0.1.0-retry-with-backoff`: retries tool_error / timeout up to 3 times with exponential backoff; aborts other kinds
  - `recovery-v0.1.1-fallback-chain`: same retry policy, plus one kind-specific fallback per failure (tool_error → alternate_tool, timeout → alternate_tool, validation_failure → structured_output_guard, model_refusal → larger_model)
- **Runner**: `runner/recovery_runner.py` with the simulation table `P_RESOLVE_BY_ACTION_AND_KIND` (Stage 2 hard-coded probabilities; Stage 3 should replace with measured values from real LLM tool-use traces)
- **UC gates**: defaults from `compute_uc_rec_gates()`
  - UC-REC-1 (completion-rate lift): >= +5.00pp
  - UC-REC-2 (cost per success vs baseline): <= 2.00x
  - UC-REC-3 (p99 task latency vs baseline): <= 3.00x
  - UC-REC-4 (max attempts per step): <= 5

## Results

| Metric | b-abort | recovery-v0.1.0-retry | recovery-v0.1.1-fallback |
|---|---|---|---|
| Scenarios | 500 | 500 | 500 |
| Completed | 353 | **450** | **486** |
| Completion rate % | 70.60 | **90.00** | **97.20** |
| Total cost | 2236.0 | 2577.0 | 2786.0 |
| Cost per completion | 6.33 | **5.73** | **5.73** |
| Latency p50 (steps) | 4.0 | 5.0 | 5.0 |
| Latency p99 (steps) | 7.0 | 9.0 | 9.0 |
| Max attempts | 1 | 4 | 4 |
| Action counts | 147 abort | 146 retry, 50 abort | 133 retry, 58 fallback, 14 abort |

### Completion by failure kind

| Failure kind | b-abort | v0.1.0 retry | v0.1.1 fallback |
|---|---|---|---|
| (none, baseline scenarios) | 100% | 100% | 100% |
| tool_error | 0% | **100%** | 98.8% |
| timeout | 0% | 72.2% | 94.4% |
| validation_failure | 0% | 0% | **92.3%** |
| model_refusal | 0% | 0% | **65.6%** |

### UC-REC gate verdicts

| Gate | v0.1.0 retry | v0.1.1 fallback |
|---|---|---|
| UC-REC-1 (lift >= +5pp) | **PASS (+19.40pp)** | **PASS (+26.60pp)** |
| UC-REC-2 (cost ratio <= 2.0x) | **PASS (0.90x)** | **PASS (0.90x)** |
| UC-REC-3 (p99 latency ratio <= 3.0x) | **PASS (1.29x)** | **PASS (1.29x)** |
| UC-REC-4 (max attempts <= 5) | **PASS (4)** | **PASS (4)** |

Both variants pass all four. fallback-chain wins on completion rate by 7.2pp while tying on cost-per-completion, latency, and attempts.

## Honest reading

### What the benchmark exposes

1. **Retry is sufficient for transient kinds and ineffective for everything else.** v0.1.0 nailed 100% of tool_errors and 72% of timeouts. It got zero on refusals and validation failures, exactly because its `retry_on_kinds` set excluded them (by design). This is the predicted behavior, but seeing it cleanly in the per-kind table is what makes the kind-aware framing defensible.
2. **Fallback recovers the kinds retry cannot touch, at modest extra cost.** v0.1.1 added 92% on validation_failure and 66% on model_refusal, with a cost-per-completion identical to v0.1.0 (5.73). The added cost of fallback steps is offset by the additional completions in the denominator.
3. **Cost per completion DROPS below baseline (0.90x) for both variants.** Counter-intuitive but mechanical: b-abort wastes cost on the steps it ran before the failure-aborted scenario (those steps still cost something but contributed to zero completions). The variants recover those scenarios, so the costs amortize over more completions.
4. **Latency tax is mild (1.29x p99) at this workload's failure rate.** A failure rate of 30% with single-failure-per-scenario keeps latency growth controlled. Higher failure rates or multi-failure scenarios should be tested in Stage 3 to see if latency growth becomes a real constraint.
5. **Max attempts stayed well under the 5-step cap.** Neither variant ever exceeded 4 attempts on any step. UC-REC-4 has slack.

### What this benchmark does NOT prove

This is exactly where the framework's "honest read" discipline matters. The numbers above pass the UC gates, but several large limitations are unaddressed:

- **The outcome simulation is hard-coded.** `P_RESOLVE_BY_ACTION_AND_KIND` uses round-number probabilities I picked to be plausible (retry-tool_error=0.7, fallback-model_refusal=0.6, etc). These are not measured from real LLM tool-use traces. Stage 3's job is to replace them. If the real probabilities are very different from these guesses, the relative ranking of variants could shift.
- **No model-size variance.** Real recovery effectiveness depends heavily on which model is running. A 3B local model has very different refusal/retry/validation behavior than gpt-4o. The framework already has the multi-model ladder primitive (`experiments/ladder_sweep_real_data.py`); Stage 3 should re-run the same workload across the ladder.
- **No real cost model.** Cost units are abstract (1 unit per step, 2.5x for fallback, 5x for ask_user). Real cost depends on model pricing per token, tool API costs, and human-in-the-loop economics. Stage 3 should plumb real $/token figures.
- **Single failure per scenario.** Real agent tasks often have cascading failures (retry succeeds but the next tool also fails). The workload generator currently injects one failure per scenario. A multi-failure workload should be added before any production claim.
- **No latency-in-seconds, only in steps.** Real latency depends on backoff wait times, model inference time, tool API roundtrips. Stage 3 should switch to a time-based latency metric.
- **No ask-user variant.** The recovery dimension includes "ask_user" as a kind, but neither pilot uses it. A v0.1.2 that escalates to human after fallback failure would close that gap.

### Did the framework's discipline transfer cleanly to this dimension?

Yes. Concrete evidence:

- Same shape as the GC opportunity (variant ABC + factory + b-noop baseline + runner + UC gates + finding doc)
- Same statistical evaluation pattern (paired comparison against baseline, gate-based pass/fail)
- Same artifact pattern (`runs/<benchmark>/<timestamp>.json`)
- Tests follow the same conventions (factory registration, per-variant decision behavior, end-to-end runner integration)
- Finding doc structure mirrors `finding-gc-stage2-revision-v0.1.2.md` and `finding-gc-stage3-real-text.md`

No framework-level changes were needed. The recovery dimension dropped into the architecture cleanly.

## Decision

**Promote v0.1.0 (retry-with-backoff) and v0.1.1 (fallback-chain) toward Stage 3.** Stage 3 should:

1. Replace the simulation table with measured probabilities from real LLM tool-use traces (highest priority)
2. Run across the multi-model ladder (gpt-4o, Claude Opus, qwen2.5:3b, etc) to surface model-family-specific recovery behavior
3. Use a real cost model based on actual token / tool / human pricing
4. Extend the workload generator to support multi-failure scenarios

If Stage 3 holds up, Stage 4 should scale to a substantial-N benchmark (5k+ scenarios) and possibly integrate with a real agent framework (LangGraph or Inspect AI) to demonstrate the policy primitives behind a familiar surface.

## What changes for v0.1.2 (deferred)

In priority order:

1. **Add `ask-user` to the fallback ladder.** When fallback fails, escalate to a human-in-the-loop step. Requires defining a cost model for human time.
2. **Sequential fallback ladder.** v0.1.1 allows one fallback per failure. v0.1.2 could allow N fallbacks with different strategies (e.g., retry → alternate_tool → larger_model → ask_user → abort).
3. **Cost-aware policy.** Make the variant aware of its own running cost and shut down early if the marginal expected lift no longer beats the marginal cost. Touches an interesting connection to the model dimension's cost optimization.

## Pointers

- Code: `runner/dimensions/recovery/{retry,fallback}.py`, `runner/recovery_runner.py`, `experiments/recovery_stage2_baseline.py`
- Workload: `fixtures/workloads/w_failure_injection.py`
- Tests: `tests/test_recovery_variants.py` (24 tests, all green) + `tests/test_failure_injection_workload.py` (16 tests, all green) = 40 recovery-dimension tests
- Day 1 verification: [`recovery-stage2-day1-verification.md`](recovery-stage2-day1-verification.md)
- Opportunity scan: [`opportunity-recovery.md`](opportunity-recovery.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Memory dimension precedents (same shape): [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md), [`finding-gc-stage3-real-text.md`](finding-gc-stage3-real-text.md)

## Reproduce

```sh
.venv/bin/python experiments/recovery_stage2_baseline.py
# Defaults: n_scenarios=500, failure_rate=0.30, seed=42.
# Runs all three variants. Writes JSON artifact to
# runs/recovery_stage2_baseline/.
```
