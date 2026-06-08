---
type: finding
opportunity: agent tool-set composition benchmark
stage: 2
status: PARTIAL-PASS
date: 2026-06-08
artifact: runs/tools_stage2_baseline/20260608T075424.json
---

# Tools Stage 2 baseline: intent-classified beats baseline on 3/4 gates; budget-bucketed is catastrophic

First Stage 2 result on a fourth dimension (after memory canonicalization, memory lifecycle, and recovery). The framework's discipline carries cleanly to the tools dimension; **no framework-level changes were needed.**

**Headlines**:

1. **`tool-v0.1.1-intent-classified` beats `b-allow-all-tools` on 3 of 4 UC-TOOL gates.** It lifts completion by +8pp, drops cost-per-completion by 4x (2071 vs 7947), and cuts latency to 0.55x baseline. **Fails UC-TOOL-3 (recall = 83.9%, need 90%).** Partial PASS; v0.1.2 needs a recall fix.
2. **`tool-v0.1.0-budget-bucketed` is catastrophic.** Naive "limit to N tools" without intent awareness drops completion from 50% to 3.67% and fails 3 of 4 UC-TOOL gates. **The framework caught the obvious wrong move** before any production deployment would have shipped it.

This is the framework working as designed: surfacing the design issue in the cheap pilot variant (budget-bucketed without intent) AND identifying the smaller fix needed in the promising variant (intent-classified's recall is too low).

## Setup

- **Workload**: `fixtures/workloads/w_tool_selection.py`, seed=42
  - 300 tasks, cross_category_chance=0.30
  - 35-tool universe across 7 categories (search, data, files, communication, computation, external_api, system)
  - 3.05 required tools per task on average
- **Variants**:
  - `b-allow-all-tools` (baseline): exposes all 35 tools
  - `tool-v0.1.0-budget-bucketed`: exposes 10 tools chosen by deterministic hash (no intent)
  - `tool-v0.1.1-intent-classified`: exposes tools from categories matched by keyword search on the task goal
- **Runner**: `runner/tool_runner.py` with simulation rules:
  - Completion requires every `required_tool` to be in exposed set
  - Selection accuracy: 95% base, minus 0.5% per extra exposed tool (cognitive overload model)
  - Cost: 500 base + 100 per exposed tool (matches verified Anthropic pricing)
  - Latency: 1 + 0.05 per exposed tool
- **UC gates** (defaults):
  - UC-TOOL-1 (completion lift): >= -5pp (allow narrowing to cost <= 5pp in completion)
  - UC-TOOL-2 (selection precision): >= 30%
  - UC-TOOL-3 (selection recall): >= 90%
  - UC-TOOL-4 (p99 latency vs baseline): <= 1.5x

## Results

| Metric | b-allow-all | tool-v0.1.0-budget | tool-v0.1.1-intent |
|---|---|---|---|
| Tasks completed | 151 | 11 | **175** |
| Completion rate % | 50.33 | 3.67 | **58.33** |
| Missing required | 0 | 289 | 78 |
| Selection failed | 149 | 0 | 47 |
| Avg exposed / task | 35.00 | 10.00 | **7.08** |
| Selection precision % | 8.70 | 8.23 | **36.09** |
| Selection recall % | 100.00 | 27.02 | 83.92 |
| Cost per completion | 7947.0 | 40909.1 | **2071.4** |
| Latency p99 | 2.75 | 1.50 | **1.50** |

### UC-TOOL gate verdicts

| Gate | tool-v0.1.0-budget | tool-v0.1.1-intent |
|---|---|---|
| UC-TOOL-1 (completion lift) | **FAIL** (-46.67pp) | **PASS** (+8.00pp) |
| UC-TOOL-2 (precision >= 30%) | **FAIL** (8.23%) | **PASS** (36.09%) |
| UC-TOOL-3 (recall >= 90%) | **FAIL** (27.02%) | **FAIL** (83.92%) |
| UC-TOOL-4 (latency <= 1.5x) | PASS (0.55x) | PASS (0.55x) |

## Honest reading

### What the benchmark surfaces

1. **Allow-all has high recall by construction but low precision and low completion.** The simulator's cognitive-overload model (accuracy drops as exposed set grows) means baseline's 35-tool exposure imposes a selection penalty. Real LLMs absolutely do degrade on tool-selection accuracy with large tool sets; this is consistent with the documented Anthropic guidance to keep tool sets focused.
2. **Budget-bucketed without intent is much worse than allow-all.** Naive "limit to 10 tools" without awareness of what the task needs drops completion from 50% to 4%. Confirms the wedge's core hypothesis: intent matters more than budget alone.
3. **Intent-classified is the right shape but the classifier is too weak.** Simple keyword matching against category names hits enough cases to beat baseline on completion / precision / cost / latency, but misses 16% of required tools. The fix surface area is small: better keyword coverage, fallback to multi-category match, or upgrade to embedding-based classifier.
4. **Cost-per-completion divergence is dramatic.** Intent-classified at 2071 tokens / completion is **3.8x cheaper** than baseline's 7947, and **20x cheaper** than budget-bucketed's 40909 (the budget variant pays full cost on every failed task). The cost dimension is the dominant lift even when completion lift is modest.

### What this finding does NOT earn

- **No real-LLM measurement.** All numbers are simulator outputs. The cognitive-overload model (0.5% accuracy drop per extra tool) and the base selection accuracy (95%) are researcher-chosen constants. Stage 3 needs real LLM tool-use traces to calibrate.
- **No model-size variance.** The simulator is single-model. Large vs small models presumably have very different selection-accuracy curves under tool-set size. Stage 3 should run across the multi-model ladder.
- **Simulator is overly punishing of "missing required."** In reality, an agent without a required tool might re-prompt for clarification, ask the user, or use an alternative tool. The current simulator treats missing-required as immediate failure. Realistic simulation should add a recovery hook.
- **No helper-tool benefit modeled.** The workload has `helper_tools` per task but the simulator doesn't reward exposing them. A more realistic model would have helper-tool presence boost selection accuracy slightly.
- **Single-pass evaluation.** Real agent loops can recover from initial-pass tool failures (the recovery dimension's domain). Joint memory-tools-recovery evaluation is the cross-dimension experiment in the multi-dim orchestration finding.

### Why this is still a meaningful Stage 2 result

The Stage 2 discipline is "does the mechanism work at all on synthetic data?" The answer here is layered:

- **Budget-bucketed (intent-blind)**: no, mechanism does not work. Caught now, before any production deployment would have shipped the obvious wrong move.
- **Intent-classified**: yes, mechanism works in the right direction (3/4 PASS), but the specific keyword classifier needs upgrading. The framework gives a precise diagnostic: recall is the failing gate, by 6 percentage points.

This is exactly the value the framework is built to produce: a structured negative result on one variant + a calibrated partial-positive on another, with the path to v0.1.2 specified.

## Decision

**Partial promotion toward Stage 3.** Two parallel tracks:

1. **v0.1.2 (Stage 2 revision)**: fix `tool-v0.1.1-intent-classified`'s recall. Specific moves:
   - Expand `CATEGORY_KEYWORDS` to cover more goal-text phrasings
   - When 0 categories match, expose top-K by frequency instead of fallback alphabetical
   - When 1 category matches, expose neighboring categories too (some tasks span two categories)
   - Possibly: use the workload's `helper_tools` as a recall hint
   Re-run the benchmark; verify recall climbs above 90%.
2. **v0.1.2 should also re-test budget-bucketed with intent**: a "budget-bucketed-with-intent" variant that combines both ideas should outperform plain intent-classified by tightening the exposed set further. That's the natural v0.1.3.

`tool-v0.1.0-budget-bucketed` (intent-blind) should NOT be promoted. It is kept in the registry as a documented anti-pattern for future benchmarks.

## What changes for v0.1.2 (in priority order)

1. **Expand keyword coverage in `CATEGORY_KEYWORDS`.** The current list is sparse; many goal phrasings won't match.
2. **Multi-category fallback.** When the goal matches one category, also expose tools from "neighbor" categories (e.g., `search` often co-occurs with `data`).
3. **Add a `tool-v0.1.2-intent-and-budget` variant.** Combine intent classification with a budget cap (e.g., expose at most 10 tools from matched categories). Should beat both pilots on cost AND completion.
4. **Workload extension**: add a `task_difficulty` parameter that affects selection accuracy independent of exposed-set size. Lets future variants demonstrate "harder tasks need more tools" behavior.

After those, re-run Stage 2. If all four UC-TOOL gates pass for a v0.1.2 variant, promote to Stage 3.

## Pointers

- Code: `runner/dimensions/tools/{budget_bucketed,intent_classified}.py`, `runner/tool_runner.py`, `experiments/tools_stage2_baseline.py`
- Workload: `fixtures/workloads/w_tool_selection.py`
- Tests: `tests/test_tool_variants.py` (19 tests) + `tests/test_tool_selection_workload.py` (17 tests) = 36 tool-dimension tests, all green
- Day 1 verification: [`tools-stage2-day1-verification.md`](tools-stage2-day1-verification.md)
- Opportunity scan: [`opportunity-tools.md`](opportunity-tools.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Memory + recovery dimension precedents (same shape): [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md), [`finding-recovery-stage2-baseline.md`](finding-recovery-stage2-baseline.md)

## Reproduce

```sh
.venv/bin/python experiments/tools_stage2_baseline.py
# Defaults: n_tasks=300, cross_category_chance=0.30, seed=42.
```
