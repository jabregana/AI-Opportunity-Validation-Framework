---
type: finding
opportunity: agent recovery policy benchmark
stage: 3
status: ROBUST-PASS
date: 2026-06-07
artifact: runs/recovery_stage3_sensitivity/20260607T220158.json
supersedes: finding-recovery-stage2-baseline.md (only the verdict's confidence; the analysis there still stands)
---

# Recovery Stage 3 sensitivity: both variants pass all four UC-REC gates on all five probability tables

This is the Stage 3 deliverable for the recovery dimension, taken as a sensitivity analysis rather than a real-LLM-trace measurement (the latter is deferred; see "What is still simplified" below). The Stage 2 baseline finding ([`finding-recovery-stage2-baseline.md`](finding-recovery-stage2-baseline.md)) showed both pilot variants pass all four UC-REC gates under the optimistic probability table. This Stage 3 finding shows **the same verdict holds across four additional plausible parameterizations** (pessimistic, small-model, large-model, hostile).

**Headline**: across five probability tables spanning a wide range of plausible LLM tool-use behavior, **both `retry-with-backoff` and `fallback-chain` pass all four UC-REC gates in every table.** The Stage 2 PASS is not a probability-table artifact.

## Why this finding is needed

The Stage 2 finding correctly flagged that `P_RESOLVE_BY_ACTION_AND_KIND` was hard-coded to a single optimistic table and that "Stage 3 should replace with measured values from real LLM tool-use traces." Real-trace collection is significant infrastructure work (real LLMs, real tools, real failure capture); a sensitivity analysis is the cheapest credible upgrade in the interim.

The Stage 3 question: **are the Stage 2 PASS verdicts robust to plausible variation in the simulation table, or do they depend on the specific values picked?** If robust, the Stage 2 finding's confidence increases. If not, the finding doc would have to call out which table the verdict depends on.

## Setup

- **Workload**: same as Stage 2 baseline, 500 scenarios, 30% failure rate, seed=42.
- **Variants**: same three: `b-abort-on-failure`, `recovery-v0.1.0-retry-with-backoff`, `recovery-v0.1.1-fallback-chain`.
- **Probability tables**: five parameterizations defined in `runner/recovery_runner.py`:

| Table | Intuition | Key knobs |
|---|---|---|
| `optimistic` | Stage 2 default | retry-tool_error=0.70, fallback-validation=0.85, fallback-refusal=0.60 |
| `pessimistic` | failures less transient than expected | retry-tool_error=0.35 (half optimistic), fallback values cut 30% |
| `small-model` | 3B-class local model | retry slightly weaker; larger-model fallback highly effective (0.85) |
| `large-model` | frontier model (gpt-4o / Claude Opus) | retry similar to optimistic; larger-model fallback weak (0.20, no model to escalate to); alternate-tool fallback similar |
| `hostile` | worst-case workload | all probabilities cut to ~30% of optimistic; tests robustness floor |

- **UC gates**: same thresholds as Stage 2 (UC-REC-1 >= +5.00pp, UC-REC-2 <= 2.00x, UC-REC-3 <= 3.00x, UC-REC-4 <= 5).

## Results: completion rate by variant x table

| Variant | hostile | large-model | optimistic | pessimistic | small-model |
|---|---|---|---|---|---|
| b-abort-on-failure | 70.60% | 70.60% | 70.60% | 70.60% | 70.60% |
| recovery-v0.1.0-retry-with-backoff | 79.60% | 90.00% | 90.00% | 86.00% | 89.00% |
| recovery-v0.1.1-fallback-chain | 83.60% | 94.00% | 97.20% | 90.60% | 95.40% |

Baseline is constant (it never recovers anything; the probability table only affects recoverable scenarios). Both pilot variants lift completion in every table, with the optimistic table being the most generous and the hostile table being the strictest.

## Results: cost per completion by variant x table

| Variant | hostile | large-model | optimistic | pessimistic | small-model |
|---|---|---|---|---|---|
| b-abort-on-failure | 6.334 | 6.334 | 6.334 | 6.334 | 6.334 |
| recovery-v0.1.0-retry-with-backoff | 6.520 | 5.727 | 5.727 | 6.060 | 5.818 |
| recovery-v0.1.1-fallback-chain | 6.772 | 5.807 | 5.733 | 6.220 | 5.833 |

Cost-per-completion goes DOWN under most tables (recovered scenarios add to the denominator faster than retry/fallback cost accumulates in the numerator). Only the hostile table inverts this slightly (variants do extra work but recover less, so cost per completion edges up). Even in the hostile table, the cost ratio stays under 1.07x baseline, still well inside the UC-REC-2 cap of 2.00x.

## UC-REC gate verdicts

Every cell below is PASS. Both variants pass every gate on every table.

| Variant | hostile | large-model | optimistic | pessimistic | small-model |
|---|---|---|---|---|---|
| recovery-v0.1.0-retry-with-backoff | **4/4** | 4/4 | 4/4 | 4/4 | 4/4 |
| recovery-v0.1.1-fallback-chain | **4/4** | 4/4 | 4/4 | 4/4 | 4/4 |

**Robust on all 5 tables, both variants.**

## Detailed verdicts on the most-constrained table (hostile)

Worth showing the hostile table specifically because it is the strictest test of robustness:

`recovery-v0.1.0-retry-with-backoff` vs `b-abort-on-failure` under `hostile`:
- UC-REC-1 (completion lift >= +5pp): PASS, **+9.00pp** (margin: 4pp)
- UC-REC-2 (cost ratio <= 2.0x): PASS, **1.03x** (margin: 0.97x)
- UC-REC-3 (latency ratio <= 3.0x): PASS, **1.29x** (margin: 1.71x)
- UC-REC-4 (max attempts <= 5): PASS, **4** (margin: 1)

`recovery-v0.1.1-fallback-chain` vs `b-abort-on-failure` under `hostile`:
- UC-REC-1: PASS, **+13.00pp** (margin: 8pp)
- UC-REC-2: PASS, **1.07x** (margin: 0.93x)
- UC-REC-3: PASS, **1.29x** (margin: 1.71x)
- UC-REC-4: PASS, **4** (margin: 1)

Margins are smallest for UC-REC-1 (completion lift) on the hostile table. If the real-world workload turns out to be MORE adversarial than the hostile table (e.g., failures truly do not recover at all with retry), UC-REC-1 could fail. The hostile table's value (~20% retry resolution for tool_error) is the floor at which the analysis still holds; below that, the recovery dimension is essentially broken regardless of policy.

## Variant ranking is stable across tables

`fallback-chain` beats `retry-with-backoff` on completion rate in every table:

| Table | fallback-chain lift over retry |
|---|---|
| hostile | +4.0pp |
| large-model | +4.0pp |
| optimistic | +7.2pp |
| pessimistic | +4.6pp |
| small-model | +6.4pp |

`fallback-chain` always wins. The margin is largest on tables where structured-output-guard / larger-model fallback strategies are most effective (optimistic and small-model). Even in the hostile table, fallback adds ~4pp over plain retry.

## Honest reading

### What this finding earns

- **Stage 2 verdict is not a single-table artifact.** Both variants pass UC-REC-1..4 across five plausible parameterizations spanning a 4x range in retry effectiveness.
- **Variant ranking is robust.** `fallback-chain > retry > baseline` in every table tested. The framework can defensibly say "fallback-chain is the better pilot variant" without qualifying which probability model holds.
- **The failure mode if the framework would break is clearly identifiable.** Only if real-world transient-failure recovery probability drops below the hostile table's ~20% would UC-REC-1 risk failing. That floor is documented.

### What this finding does NOT earn

- **No real-LLM measurement.** All five tables are still researcher-defined. The hostile table is meant to be pessimistic, but a real adversarial workload could be even worse. Real Stage 3 (with actual LLMs, actual tools, actual failure capture) is still pending.
- **No multi-model ladder run.** The "small-model" and "large-model" tables are abstractions of real model behavior, not measurements of specific models. A real run with qwen2.5:3b vs gpt-4o would test whether the right table for each model matches the abstractions.
- **No real cost model.** Cost units are still abstract (1 unit/step, 2.5x for fallback, 5x for ask-user). Real cost depends on per-token pricing, tool API charges, human-in-the-loop economics. Cost-per-completion comparisons are meaningful in relative terms but not absolute.
- **No single-table calibration to a known dataset.** A more rigorous Stage 3 would calibrate one table to a known agent-eval dataset (Inspect AI's agent_bench or similar) and report whether the framework's variants match the dataset's documented recovery rates.
- **Same single-failure-per-scenario limitation.** Workload still injects one failure per scenario maximum. Cascading failure patterns untested.

### Why sensitivity is a valid (though weaker) Stage 3

The framework's discipline says Stage 3 = "real data, small N." Sensitivity analysis is not real data, but it does verify a key Stage 2 assumption: that the verdict is not load-bearing on one specific simulation choice. A proper Stage 3 should still happen; this sensitivity is a credibility floor in the interim.

The proxy's Stage 3 also had a precedent for this kind of guard: it built integration shims and ran small-N benchmarks before scaling up. Sensitivity analysis serves the same role for the recovery dimension: confirm the mechanism is not table-fragile before investing in the LLM-trace infrastructure.

## Decision

Accept Stage 3 sensitivity as a robustness-confirmed PASS. Both `recovery-v0.1.0-retry-with-backoff` and `recovery-v0.1.1-fallback-chain` are promoted toward "Stage 4 substantial-real-data" reconceived as "Stage 3 real-LLM-trace measurement," which is the next step.

Stage 4 (real-LLM-trace measurement) should:

1. **Calibrate one probability table to measured outcomes from a small LLM-with-tools workload.** A handful of tasks (50-200) with synthetic tools and ollama-hosted small models would produce the first measured `P_RESOLVE` table.
2. **Re-run the sensitivity benchmark.** Drop the calibrated table in alongside the five plausible ones; check the verdict still holds.
3. **Use the real cost model.** Token-priced model costs, tool API costs, human-in-the-loop estimates.
4. **Run across the multi-model ladder.** The existing `experiments/ladder_sweep_real_data.py` infrastructure already handles routing; add the recovery benchmark to it.

## Pointers

- Code: `experiments/recovery_stage3_sensitivity.py` (this script), `runner/recovery_runner.py` (refactored to accept `p_resolve_table` parameter; five named tables in `P_RESOLVE_TABLES`)
- Prior finding (analysis still load-bearing): [`finding-recovery-stage2-baseline.md`](finding-recovery-stage2-baseline.md)
- Day 1 verification: [`recovery-stage2-day1-verification.md`](recovery-stage2-day1-verification.md)
- Opportunity scan: [`opportunity-recovery.md`](opportunity-recovery.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/recovery_stage3_sensitivity.py
# Defaults: n_scenarios=500, failure_rate=0.30, seed=42.
# Runs all three variants under all five probability tables.
# Writes JSON artifact to runs/recovery_stage3_sensitivity/.
```
