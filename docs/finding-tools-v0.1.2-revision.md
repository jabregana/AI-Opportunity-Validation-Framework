---
type: finding
opportunity: agent tool-set composition benchmark
stage: 2
status: STILL-PARTIAL-PASS
date: 2026-06-08
artifact: runs/tools_stage2_baseline/20260608T081013.json
supersedes: finding-tools-stage2-baseline.md (only the verdict's path-forward; the analysis there still stands)
---

# Tools v0.1.2 revision: recall climbed but still under threshold; cross-dim still negative

This finding documents the v0.1.2 attempt at fixing the recall gap flagged in [`finding-tools-stage2-baseline.md`](finding-tools-stage2-baseline.md). The revision improves recall meaningfully (83.92% to 89.82%) but still falls 0.18pp short of the UC-TOOL-3 90% threshold, and the cross-dim experiment still shows the joint deployment trails baseline. **The framework continues to refuse a deployment recommendation that would harm production.**

## What v0.1.2 changes

Three fixes in `runner/dimensions/tools/intent_plus.py` (registered as `tool-v0.1.2-intent-plus-helper`):

1. **Expanded keyword coverage**: from ~6 keywords per category in v0.1.1 to ~11-14, covering more real-world task phrasings.
2. **Neighbor category expansion**: when a category matches, also expose tools from neighbor categories (e.g., `search` ↔ `data`, `files` ↔ `system`).
3. **Helper-tool hint**: include tools from `task.helper_tools` in the exposed set (proxies for a real similarity classifier surfacing additional candidates).

## Results

| Metric | b-allow-all | v0.1.1 | **v0.1.2** |
|---|---|---|---|
| Completion rate % | 50.33 | 58.33 | 54.67 |
| Avg exposed / task | 35.00 | 7.08 | 17.09 |
| Selection precision % | 8.70 | 36.09 | **16.01** |
| Selection recall % | 100.00 | 83.92 | **89.82** |
| Cost per completion | 7947.0 | 2071.4 | 4041.5 |
| Latency p99 | 2.75 | 1.50 | 2.30 |

### UC-TOOL gate verdicts

| Gate | v0.1.1 | **v0.1.2** |
|---|---|---|
| UC-TOOL-1 (completion >= -5pp) | PASS (+8.00pp) | PASS (+4.33pp) |
| UC-TOOL-2 (precision >= 30%) | PASS (36.09%) | **FAIL** (16.01%) |
| UC-TOOL-3 (recall >= 90%) | **FAIL** (83.92%) | **FAIL** (89.82%) |
| UC-TOOL-4 (latency <= 1.5x) | PASS (0.55x) | PASS (0.84x) |

v0.1.2 fixes UC-TOOL-3 by 6 percentage points (still 0.18pp under threshold) but **introduces a UC-TOOL-2 failure** because the neighbor expansion roughly doubles the exposed set size, diluting precision from 36% to 16%.

### Cross-dim re-run with v0.1.2

Same workload as [`finding-cross-dim-interaction.md`](finding-cross-dim-interaction.md), 500 scenarios, seed=42:

| Config | Completion % | P_tools |
|---|---|---|
| all-baselines | 36.80 | 1.000 |
| best-with-v0.1.1 (cot+structured, intent-classified, fallback) | 25.00 | 0.426 |
| **best-with-v0.1.2** (cot+structured, **intent-plus-helper**, fallback) | **31.00** | **0.528** |

v0.1.2 lifts the joint config from 25% to 31% (+6pp), but **still trails baseline (37%) by -6pp.** The multiplicative composition remains the dominant constraint. Even at 89.82% recall, P_tools=0.528 (averaged over scenarios) multiplies through every other dimension and produces a net loss.

## Honest reading

### What v0.1.2 surfaces

1. **Simple keyword classification is approaching its ceiling.** v0.1.0 (no intent) had 27% recall. v0.1.1 (basic intent) had 84%. v0.1.2 (expanded intent + neighbors + helpers) reached 90%. The marginal lift per fix is shrinking. Hitting the 90% gate cleanly likely needs a different mechanism (embedding similarity, LLM classifier) rather than more keywords.

2. **Recall-precision trade-off is now visible.** v0.1.1 was high precision (36%) / low recall (84%). v0.1.2 swaps: low precision (16%) / high recall (90%). The Pareto frontier of (precision, recall) is visible; no single keyword-based variant dominates.

3. **Multiplicative composition is unforgiving.** Improving P_tools from 0.426 to 0.528 lifted cross-dim completion by only 6pp. To beat baseline by 5pp (matching individual dimension's UC gates), P_tools needs to be ~0.95+. At 90% per-scenario recall, the AVERAGE P_tools is still well below 0.95 because some scenarios have partial recall.

4. **The framework still recommends NOT shipping a tools variant.** Even with v0.1.2's improvements, the joint deployment is worse than no variants. The cross-dim experiment continues to function as the gatekeeper.

### What v0.1.2 does NOT earn

- **No UC-TOOL-3 pass.** 89.82% < 90% threshold. Technically still PARTIAL-PASS.
- **No precision pass.** UC-TOOL-2 now fails as a side effect of neighbor expansion.
- **No positive cross-dim verdict.** Best-with-v0.1.2 at 31% still < baseline at 37%.

### What v0.1.3 should do (deferred)

Three candidate directions, none committed:

1. **Embedding-based classifier.** Replace keyword matching with a sentence-embedding similarity between the goal and category descriptions. Should hit 95%+ recall on the synthetic workload because every template phrasing maps cleanly to a category embedding.
2. **Tighter neighbor expansion.** v0.1.2 expands every match's neighbors. A smarter variant could expand only when classification is uncertain (one or zero categories matched). An earlier experiment with this idea hurt recall instead of helping precision; needs more thought.
3. **Per-scenario adaptive budget.** Expose all matched categories plus their neighbors only up to a budget cap (e.g., max 12 tools). Trade off recall ceiling against precision floor explicitly.

The honest framing: the keyword-classification mechanism may have a ceiling around 90% on this workload. Embedding-based classification is probably the right v0.1.3.

## Decision

**Maintain the "do NOT ship tools variants yet" recommendation from the cross-dim finding.** v0.1.2 is a meaningful improvement (recall +5.9pp, cross-dim +6pp) but does not close the gap. Continue to keep v0.1.0 / v0.1.1 / v0.1.2 in the registry as documented partial solutions; promote NONE to Stage 3 yet.

The next iteration should attempt v0.1.3 with an embedding-based classifier before any Stage 3 work.

## What this iteration validates about the framework

Two operational signals worth flagging:

1. **The framework's gate-based discipline is doing its job.** v0.1.2's recall improvement looks like progress, but the UC-TOOL-2 precision drop and the cross-dim still-negative result mean the variant is not deployable. Without the harness, the recall improvement might have been enough to ship.

2. **Cross-dim is now an established gatekeeper.** This is the second cross-dim run (after [`finding-cross-dim-interaction.md`](finding-cross-dim-interaction.md)) and it has produced an actionable verdict both times. The "add cross-dim verification to every Stage 3" recommendation from the first cross-dim finding is now load-bearing on actual decisions.

## Pointers

- Code: `runner/dimensions/tools/intent_plus.py` (the variant), `experiments/tools_stage2_baseline.py` (updated to include v0.1.2)
- Prior finding (analysis still load-bearing): [`finding-tools-stage2-baseline.md`](finding-tools-stage2-baseline.md)
- Cross-dim experiment (the gatekeeper): [`finding-cross-dim-interaction.md`](finding-cross-dim-interaction.md)
- Opportunity scan: [`opportunity-tools.md`](opportunity-tools.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/tools_stage2_baseline.py
# Defaults: n_tasks=300, cross_category_chance=0.30, seed=42.
# Now includes tool-v0.1.2-intent-plus-helper in the variant list.
```
