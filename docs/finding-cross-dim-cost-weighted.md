---
type: finding
opportunity: cross-dimension orchestration
stage: experiment
status: PARETO-FRONTIER-IDENTIFIED
date: 2026-06-08
artifact: runs/cross_dim_cost_weighted/20260608T085441.json
---

# Cross-dim cost-weighted matrix + bootstrap CIs: top of leaderboard is statistically tied

Extends the [`finding-cross-dim-full-matrix.md`](finding-cross-dim-full-matrix.md) experiment with two additions:

1. **Per-config cost tracking**: prompt tokens (from rendered prompt) + tool tokens (100 per exposed) + recovery overhead tokens (retry/fallback). Cost-per-completion is now first-class.
2. **Bootstrap 95% confidence intervals** on the completion rate for every config (500 resamples each).

**Headlines**:

1. **6 of the top-10 by completion have CIs that overlap with #1's.** Most of the top is statistically tied; the framework's previous "ship few-shot-3" recommendation should be moderated.
2. **The Pareto frontier (cost, completion) has 5 configs.** Two cluster at the high-completion end (60.20% and 59.60%); three clusters at lower completion / lower cost.
3. **Top-1 (`few-shot-3`) and top-2 (`cot-plus-structured`) are statistically indistinguishable.** #2 is also slightly cheaper. **#2 is the better deployment choice when you account for both signal and cost.**
4. **All top-of-cost-per-completion configs are LOW completion** (~21-25%). Cheap per-completion is meaningless if you complete only one in four tasks. This is the classic "false economy" trap; the cost-weighted analysis surfaces it.

## Setup

- **Workload**: same as [`finding-cross-dim-full-matrix.md`](finding-cross-dim-full-matrix.md): 500 scenarios, 30% failure rate, seed=42
- **Matrix**: 72 configs (6 prompt x 4 tools x 3 recovery)
- **Cost model**: `prompt_tokens + tool_tokens + recovery_tokens` per scenario; cost-per-completion = total / n_completed
- **CI**: 500-resample bootstrap on each config's per-scenario binary outcomes; 95% confidence

## Pareto frontier (5 configs)

| Compl % | CI (lo-hi) | Cost/comp | Prompt | Tools | Recovery |
|---|---|---|---|---|---|
| **60.20%** | [55.8-64.0] | 6223.8 | few-shot-3 | b-allow-all | fallback-chain |
| **59.60%** | [55.0-63.6] | 6194.2 | cot-plus-structured | b-allow-all | fallback-chain |
| 31.00% | [26.6-35.0] | 5131.4 | cot-plus-structured | intent-plus-helper | fallback-chain |
| 25.40% | [22.0-29.0] | 4502.9 | few-shot-3 | intent-classified | fallback-chain |
| 25.00% | [21.4-28.6] | 4355.0 | cot-plus-structured | intent-classified | fallback-chain |

The Pareto frontier confirms the previous finding's qualitative recommendation: at the high-completion end, the best deployable configs both use `b-allow-all-tools + fallback-chain`. The difference between `few-shot-3` and `cot-plus-structured` is small in completion and even smaller in cost.

## Top 10 by completion (with bootstrap CIs)

| Rank | Compl % | CI (lo-hi) | Cost/comp | Prompt | Tools | Recovery |
|---|---|---|---|---|---|---|
| 1 | 60.20% | [55.8-64.0] | 6223.8 | few-shot-3 | b-allow-all | fallback-chain |
| 2 | 59.60% | [55.0-63.6] | 6194.2 | cot-plus-structured | b-allow-all | fallback-chain |
| 3 | 56.20% | [51.4-60.4] | 6545.4 | cot | b-allow-all | fallback-chain |
| 4 | 56.20% | [51.4-60.2] | 6567.2 | few-shot-1 | b-allow-all | fallback-chain |
| 5 | 55.20% | [51.0-59.6] | 6680.7 | few-shot-3 | b-allow-all | retry-with-backoff |
| 6 | 54.40% | [50.2-58.8] | 6677.8 | cot-plus-structured | b-allow-all | retry-with-backoff |
| 7 | 53.40% | [48.8-57.6] | 6873.1 | direct-structured | b-allow-all | fallback-chain |
| 8 | 51.40% | [47.0-55.6] | 7065.7 | few-shot-1 | b-allow-all | retry-with-backoff |
| 9 | 51.00% | [46.6-55.4] | 7097.1 | cot | b-allow-all | retry-with-backoff |
| 10 | 50.40% | [46.0-54.8] | 7255.9 | b-default | b-allow-all | fallback-chain |

**6 of 9 configs below #1 have CIs that overlap with #1's CI [55.8-64.0].** The framework cannot claim statistical superiority of #1 over those 6. Specifically: configs #2 through #7 all overlap.

## Top 10 by cost-per-completion (cheapest first)

| Rank | Cost/comp | Compl % | CI (lo-hi) | Prompt | Tools | Recovery |
|---|---|---|---|---|---|---|
| 1 | 4355.0 | 25.00% | [21.4-28.6] | cot-plus-structured | intent-classified | fallback-chain |
| 2 | 4502.9 | 25.40% | [22.0-29.0] | few-shot-3 | intent-classified | fallback-chain |
| 3 | 4556.4 | 22.60% | [19.0-25.8] | cot-plus-structured | intent-classified | retry-with-backoff |
| ... | ... | ... | ... | ... | ... | ... |

**False economy alert**: every top-10 by cost-per-completion uses `tool-v0.1.1-intent-classified` and ALL have completion below 26%. They are cheap per task completed because they complete so few tasks (the inverse of what cost-per-completion should reward).

The right ranking for deployment is the **Pareto frontier**, not raw cost-per-completion. The Pareto frontier excludes the false-economy configs and keeps only those that are non-dominated on both axes.

## Honest reading

### What the bootstrap CIs change

- **The framework's "ship few-shot-3" recommendation from the previous matrix finding is over-precise.** few-shot-3 (60.20%, CI [55.8-64.0]) and cot-plus-structured (59.60%, CI [55.0-63.6]) overlap heavily. There is no statistical basis for picking one over the other on completion alone.
- **cot-plus-structured is the better choice** when cost is factored in: 59.60% completion at 6194.2 cost/comp vs 60.20% at 6223.8. Statistically tied on completion + cheaper = preferred.
- **The bottom-10 are clearly distinguishable from the top-10**. The CIs for bottom-rank configs (11-15% completion) do not overlap with top-rank configs (50-60%). The framework's verdict that "75% of configs lose vs baseline" is robust to bootstrap variance.

### What the cost-weighting changes

- **The "cheapest cost-per-completion" ranking is uninformative on its own.** Without a completion-rate floor, cost-per-completion rewards configs that fail more often (fewer completions but also fewer expensive operations).
- **Pareto frontier is the actionable artifact.** Five configs are Pareto-optimal; everything else is dominated. The deployment choice is between those 5.
- **High-completion-Pareto and low-cost-Pareto are different deployment regimes.** The two clusters in the Pareto frontier represent different operating budgets:
  - "Quality budget": ~60% completion at ~6200 cost/comp (2 configs)
  - "Tight budget": ~25-31% completion at ~4400-5100 cost/comp (3 configs)

### What this finding does NOT earn

- **No real-LLM measurement.** All numbers are still simulator outputs. The cost model is a researcher-chosen approximation (100 tokens per tool matches Anthropic's documented pricing, but per-task input/output mix in real use varies).
- **No engineering-cost weighting.** The "cost" here is per-call inference cost (tokens). The engineering cost to build each variant (the analyst's "2 engineers for 3 months" framing) is not in this analysis. That is the next major addition (see [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md) proposal 1).
- **No business-KPI overlay.** Completion-rate lift does not convert to revenue, conversion, or deflection metrics. That bridge is also a planned next addition.

### Why this finding matters for the framework's positioning

The bootstrap CIs and the Pareto frontier together convert the framework's output from "research report" to "deployment-grade recommendation":

- Before: "few-shot-3 wins" (point estimate, no confidence)
- After: "cot-plus-structured is statistically tied with few-shot-3 and slightly cheaper, so pick that" (CI-aware, cost-aware)

This is one of the bridge layers the analyst review flagged as missing (statistical effect + cost-aware ranking). It positions the framework closer to the "decision tool" framing.

## Decision: refined deployment recommendation

The framework's recommended deployment is now:

| Dimension | Recommended variant | Rationale |
|---|---|---|
| Prompt | `prompt-v0.1.4-cot-plus-structured` | Statistically tied with few-shot-3 on completion; slightly cheaper |
| Tools | `b-allow-all-tools` | All non-baseline tools variants are dominated; baseline wins by 25-35 percentage points on rolled-up averages |
| Recovery | `recovery-v0.1.1-fallback-chain` | Highest rolled-up completion across all (prompt, tools) combinations |

Expected joint completion: 59.60% (CI [55.0-63.6]) at 6194.2 cost-per-completion.

## What this enables (and what's still missing)

The cost-weighted matrix + CIs are the foundation for an **investment-prioritization tool** (proposal 3 in [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)). That tool needs two more inputs the framework does not yet have:

1. **Engineering build-cost per variant.** A field on every `*Variant` class estimating "this took N engineer-weeks." Adding it is a few hours; doing it credibly requires retrospective audit of which variants took how long.
2. **Business-KPI mapping per opportunity.** A doc per opportunity bridging "completion lift" to candidate revenue / conversion / deflection metrics.

With those two inputs plus the cost-weighted matrix, the framework outputs a ranked investment list with ROI per dollar spent. That is the "budget allocation tool" framing.

## Pointers

- Code: `experiments/cross_dim_cost_weighted.py`, `runner/cross_dim_runner.py` (refactored to expose per-scenario outcomes + cost tracking)
- Prior cross-dim finding: [`finding-cross-dim-full-matrix.md`](finding-cross-dim-full-matrix.md)
- Strategic positioning: [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/cross_dim_cost_weighted.py
# Defaults: n_scenarios=500, failure_rate=0.30, seed=42, n_bootstrap=500.
# Runs all 72 configs with bootstrap CIs; writes JSON artifact.
```
