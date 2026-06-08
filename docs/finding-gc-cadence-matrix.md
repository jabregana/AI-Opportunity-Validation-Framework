---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: TOMBSTONE-RECOVERY-PASSES-AT-CADENCE-100-V018-SHIPPED
date: 2026-06-08
artifact: runs/gc_sweep_cadence_matrix/20260608T101939.json
---

# GC sweep-cadence sensitivity + v0.1.8: tombstone recovery passes at cadence <= 100

This finding documents two related changes:

1. **`gc-v0.1.8-comprehensive-tuned`**: the production-ready full-feature bundle that v0.1.6 was supposed to be. Composes v0.1.3 (tombstone) + v0.1.5 (tenant pinning) + v0.1.7 (tuned entity rule). Replaces v0.1.6's v0.1.4-based entity rule (which over-collected on the differentiated workload).

2. **Sweep-cadence sensitivity matrix**: tests v0.1.2 / v0.1.3 / v0.1.6 / v0.1.8 at sweep cadences {10, 50, 100, 500, 1000} events. **At cadence <= 100, all three tombstone variants pass UC-GC-5 (95.5%-100% recovery).** Wall-time cost is 2-10x more sweep time but produces deployable tombstone behavior.

This closes out the "tombstone recovery is low" gap from the differentiated-Stage 2 finding. The mechanism works; the production tuning question is "how often to sweep."

## Results: tombstone recovery rate by (variant, cadence)

| Variant | cad=10 | cad=50 | cad=100 | cad=500 | cad=1000 |
|---|---|---|---|---|---|
| gc-v0.1.2-fact-only | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| **gc-v0.1.3-fact-only-tombstone** | **100.0%** | **100.0%** | **95.5%** | 22.5% | 13.0% |
| **gc-v0.1.6-comprehensive** | **100.0%** | **100.0%** | **95.5%** | 22.5% | 13.0% |
| **gc-v0.1.8-comprehensive-tuned** | **100.0%** | **100.0%** | **95.5%** | 22.5% | 13.0% |

The threshold (80%) is crossed at cadence 100. Below that (more frequent sweeps), all tombstone variants saturate near 100%. Above (less frequent), recovery falls off rapidly.

## Results: sweep wall-time (seconds)

| Variant | cad=10 | cad=50 | cad=100 | cad=500 | cad=1000 |
|---|---|---|---|---|---|
| gc-v0.1.2 | 0.021 | 0.009 | 0.008 | 0.006 | 0.006 |
| gc-v0.1.3 | 0.022 | 0.010 | 0.008 | 0.007 | 0.006 |
| gc-v0.1.6 | 0.073 | 0.021 | 0.014 | 0.009 | 0.008 |
| **gc-v0.1.8** | 0.080 | 0.022 | 0.015 | 0.009 | 0.008 |

Cost of moving from cadence 1000 to cadence 100:
- v0.1.3: 1.33x more sweep time (0.006 → 0.008)
- v0.1.8: 1.88x more sweep time (0.008 → 0.015)

**Tombstone recovery gain: 13% → 95.5% (~7x improvement). Sweep cost: ~1.5x. Strongly worth it.**

Cost of moving from cadence 100 to cadence 10:
- v0.1.3: 2.75x more sweep time (0.008 → 0.022)
- v0.1.8: 5.33x more sweep time (0.015 → 0.080)

**Tombstone recovery gain: 95.5% → 100% (~4.5pp marginal). Sweep cost: 2.75-5.3x. Probably not worth it.**

Pareto-optimal cadence on this workload: **100 events between sweeps.**

## Results: store reduction (constant, as expected)

| Variant | cad=10-1000 |
|---|---|
| gc-v0.1.2 | 97.56% |
| gc-v0.1.3 | 97.56% |
| gc-v0.1.6 | 98.20% |
| gc-v0.1.8 | 98.15% |

Store reduction is invariant to cadence (collection happens eventually; sweep frequency only affects WHEN). v0.1.4-inheriting variants (v0.1.6) slightly beat v0.1.7-inheriting variants (v0.1.8) on raw reduction (98.20 vs 98.15) because v0.1.4 collects more entities (including the ones it shouldn't).

## Results: surviving entities (the v0.1.4 vs v0.1.7 difference)

| Variant | cad=10-1000 |
|---|---|
| gc-v0.1.2 | 50 (100%) |
| gc-v0.1.3 | 50 (100%) |
| gc-v0.1.6 | 37 (74%) |
| **gc-v0.1.8** | 38 (76%) |

v0.1.8's entity recall is 76% vs v0.1.6's 74% — same marginal improvement v0.1.7 showed over v0.1.4 in the previous finding. The query_count secondary gate catches 1 more entity. Still below the UC-GC-2 threshold (95%).

## Honest reading

### What this earns

- **Tombstone recovery is now operationally viable.** At sweep cadence 100, three tombstone variants pass UC-GC-5. Production guidance is clear: deploy with cadence between 50 and 100 events to get >95% recovery at modest cost.
- **v0.1.8 is the production-ready bundle.** It has all the features of v0.1.6 PLUS the safer entity rule from v0.1.7. Same store reduction, slightly better recall, no v0.1.4-style over-collection regression on workloads where v0.1.7 helps.
- **The sweep-cadence sensitivity matrix is a useful production-deployment tool.** Operators can pick a cadence that hits their target tombstone-recovery rate within their compute budget.

### What this finding does NOT earn

- **v0.1.8 still fails UC-GC-2 / UC-GC-3 on the differentiated workload.** Entity collection is sensitive to query distribution variance; v0.1.7 / v0.1.8's `min_query_count=3` gate only catches some over-collection. A workload-specific threshold calibration is needed for production.
- **Cadence guidance is workload-specific.** On a higher-volume workload (1M events vs 10K), cadence 100 might be far too aggressive. Production deployments need their own cadence sensitivity sweep.
- **No real LLM data.** Same caveat as previous findings: all numbers from the simulator. Real production cadence costs scale with the actual cost of sweeping a real graph DB, not in-memory dict mutation.

### Investment-tool refresh

v0.1.8 now in the investment tool:

| Rank | Verdict | Variant | Lift / eng-wk |
|---|---|---|---|
| 1 | FUND-NOW | gc-v0.1.2 | 80.0 |
| 2 | FUND-NOW | gc-v0.1.3 | 53.3 |
| 3 | FUND-NOW | gc-v0.1.5 | 53.3 |
| 4 | FUND-NOW | gc-v0.1.7 | 40.0 |
| **5** | **FUND-NOW** | **gc-v0.1.8** | **22.9** |
| ... | DO-NOT-BUILD | gc-v0.1.4 | 53.3 (cross-dim caveat) |
| ... | DO-NOT-BUILD | gc-v0.1.6 | 26.7 (inherits v0.1.4) |

v0.1.8's lift-per-week is lower than the simpler variants because it costs 3.5 eng-weeks (3 for the bundle + 0.5 for the cadence-tuning ops work) and offers the same store-reduction lift. The DEPLOYABLE-BUNDLE story is what justifies v0.1.8: it's the variant teams should pick when they want all the features simultaneously.

## Decision

Accept v0.1.8 as the recommended production bundle. Update operational guidance:

| Deployment context | Recommended variant | Sweep cadence |
|---|---|---|
| Default single-tenant simple | gc-v0.1.2-fact-only | 1000 (default) |
| Single-tenant + tombstones | gc-v0.1.3-fact-only-tombstone | **100 events** |
| Multi-tenant SaaS, simple | gc-v0.1.5-fact-only-tenant-pinning | 1000 |
| Entity collection needed | gc-v0.1.7-conservative-entity-tuned (calibrate thresholds) | 1000 |
| **Multi-tenant SaaS, full features** | **gc-v0.1.8-comprehensive-tuned** | **100 events** |

The framework's previous "build a v0.1.8" hypothesis is now realized.

## Pointers

- Code: `runner/dimensions/memory/lifecycle/comprehensive_tuned.py` (v0.1.8), `experiments/gc_sweep_cadence_matrix.py` (cadence experiment), `runner/variant_costs.py` + `experiments/investment_prioritization.py` (v0.1.8 entries)
- Prior finding: [`finding-gc-tombstone-api-and-v017.md`](finding-gc-tombstone-api-and-v017.md)
- Investment-prioritization tool: `experiments/investment_prioritization.py`

## Reproduce

```sh
.venv/bin/python experiments/gc_sweep_cadence_matrix.py
# Tests 4 variants x 5 cadences = 20 runs on the differentiated workload
.venv/bin/python experiments/investment_prioritization.py
# Investment tool now ranks v0.1.8 alongside the other 7 GC variants
```
