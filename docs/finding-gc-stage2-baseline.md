---
type: finding
opportunity: real-time graph GC for agent memory
stage: 2
status: BASELINE-NEGATIVE
date: 2026-06-07
artifact: runs/gc_stage2_baseline/20260607T181744.json
---

# Stage 2 baseline finding: ref-count GC variants do not pass UC-GC-2

The first Stage 2 benchmark for the graph-GC opportunity (Niche 3 in the original landscape scan, scoped in [`opportunity-graph-gc.md`](opportunity-graph-gc.md)) ran the three pilot variants against the synthetic graph-churn workload. The honest read: **both GC variants fail the surviving-entity recall gate (UC-GC-2) on this workload, the store-size reduction is trivial (2.2%), and the two non-baseline variants are indistinguishable from each other.**

This is a Stage 2 negative finding. Do not promote to Stage 3. The framework caught two design issues and one workload/gate-design issue before any real-data effort.

## Setup

- **Workload**: `fixtures/workloads/w_graph_churn.py`, generated with seed=42
  - 50 entities, 2000 facts, fact_lifetime=7 days, pin_fraction=0.10, query_fraction=0.15
  - 10,435 events total, 5 pinned nodes, 5 expected survivors
- **Variants**:
  - `b-raw-no-gc` (baseline, never collects)
  - `gc-v0.1.0-ref-count` (collect entity with in_degree==0 AND age > 7d)
  - `gc-v0.1.1-ref-count-utility` (v0.1.0 + utility-score rule for entities)
- **Runner**: `runner/gc_runner.py` with default `sweep_every_n_events=1000`
- **UC gates**: defaults from `compute_uc_gates()`
  - UC-GC-1 (store reduction): >= 0%
  - UC-GC-2 (surviving-entity recall vs baseline): >= 95%
  - UC-GC-3 (false-collection rate): <= 1%
  - UC-GC-4 (write-path p99): <= 10 ms

## Results

| Metric | b-raw-no-gc | gc-v0.1.0 | gc-v0.1.1 |
|---|---|---|---|
| Nodes added | 2050 | 2050 | 2050 |
| Nodes collected | 0 | 45 | 45 |
| Nodes at end | 2050 | 2005 | 2005 |
| Store reduction % | 0.00 | **2.20** | **2.20** |
| Surviving entities | 50 | **5** | **5** |
| False collections | 0 | 0 | 0 |
| Write p50 (ms) | 0.0002 | 0.0002 | 0.0002 |
| Write p99 (ms) | 0.0004 | 0.0003 | 0.0003 |
| Sweep total (s) | 0.0002 | 0.0009 | 0.0018 |

### UC gate verdicts

| Gate | gc-v0.1.0 | gc-v0.1.1 |
|---|---|---|
| UC-GC-1 (store reduction) | PASS (trivial: threshold is 0%) | PASS (trivial) |
| UC-GC-2 (entity recall vs baseline) | **FAIL** (10%, need 95%) | **FAIL** (10%, need 95%) |
| UC-GC-3 (false-collection rate) | PASS (0%) | PASS (0%) |
| UC-GC-4 (write p99 latency) | PASS (0.0003 ms) | PASS (0.0003 ms) |

UC-GC-2 fails because both variants collected 45 of the 50 entities, keeping only the 5 pinned ones.

## Honest reading

### Five issues this surfaced

1. **Store reduction is trivial (2.2%) because facts dominate the store and the variants never collect them.** The workload generates 2000 facts plus 50 entities. The ref-count rule deliberately excludes facts (the design comment in `ref_count.py:46-48` says facts are "the write-stream record" and stay even after their edges are removed). Result: even after a fact's edge has been removed (mimicking supersession), the fact node persists forever. Most of the store is dead-edge facts.

   **Implication for v0.1.2**: add a fact-collection rule. The simplest version is "collect a fact node whose outgoing-edge count has dropped to 0." That would let dead facts age out alongside their references.

2. **UC-GC-2 fails hard because the orphan rule is too aggressive for entities, given how the workload models edge lifetime.** The workload removes a fact's edges after `fact_lifetime` (7d). After all of an entity's facts have aged out, the entity has in_degree=0 and the variant collects it on the next sweep. In the running workload, this happens to 45 of the 50 non-pinned entities by run-end.

   This is partly a real design issue (entities are long-lived concepts that should not disappear just because their recent mentions aged out) and partly a workload-vs-gate design contradiction (see issue 4).

   **Implication for v0.1.2**: entities probably need a much longer min_age_seconds (e.g., 90 days) OR a demotion mechanism (move to cold storage) rather than collection OR a separate query-recency floor before any collection is allowed.

3. **v0.1.1 utility variant is observationally identical to v0.1.0 on this workload.** Same nodes collected, same store-size, same UC gates. The utility rule never fires because the orphan rule covers all the same candidates first.

   **Implication for the next workload**: design a variant of the churn workload where some entities retain edges but are never queried (so utility rule can distinguish them from query-active entities). Without that, v0.1.1's added complexity is invisible.

4. **The workload's `expected_survivors` set and the UC-GC-2 gate's baseline-comparison logic encode contradictory assumptions.** The generator currently sets `expected_survivors == pinned_nodes` (5 nodes). UC-GC-2 implicitly assumes all entities should survive (it compares variant's surviving entities against baseline's, where baseline kept all 50). These two are not consistent.

   **Implication**: pick one philosophy and apply it everywhere. Either:
   - **Strict survival** (only pinned): then the workload and the gates agree, but UC-GC-2 should not compare against b-raw's full entity set; it should compare against `expected_survivors`. Most variants will pass trivially.
   - **Conservative survival** (entities long-lived): then `expected_survivors` should include all entity nodes by default, and the variants need much more conservative collection rules.
   The current code mixes both. The next finding doc should pick one and update the workload generator + gate definition together.

5. **Write-path latency is sub-microsecond, so UC-GC-4 passes trivially.** With 10,435 events and per-event timing under 0.001 ms, the workload does not stress the write path. UC-GC-4 will only be meaningful on a workload large enough to exercise the in-degree-update hot path under real concurrency, or on a real-data workload where the integrated downstream (Neo4j / Memgraph / Graphiti) actually owns the write latency.

### What the framework did correctly

- The pinned-node protection works (false-collection rate is 0% across both variants).
- The runner records what it claims (latencies, sweep timing, surviving entity ids, falsely collected ids).
- The UC gate evaluation surfaces the right failure (UC-GC-2 fails loudly).
- The seed-deterministic workload makes the failure reproducible.

This is the framework working: a synthetic workload + a UC-gate suite forced a design conversation before any real-data benchmark spent effort confirming a flawed variant.

## Decision

**Do not promote to Stage 3.** The current variant family does not pass Stage 2 on this workload. The next iteration is a Stage 2 revision, not a Stage 3 real-data run.

## What changes for v0.1.2

In priority order:

1. **Add fact-collection rule.** Collect a fact node whose outgoing edges have all been removed. This is the largest store-reduction lever (facts are 2000 of 2050 nodes).
2. **Reconcile `expected_survivors` with UC-GC-2 semantics.** Pick the strict-or-conservative philosophy in writing (update `opportunity-graph-gc.md`). Update both the workload generator's `expected_survivors` computation and the gate's baseline-comparison logic to match. Re-run the baseline.
3. **Tighten the entity orphan rule.** Either raise `min_age_seconds` to 90 days, or add a "must have had zero queries for X days" precondition, or replace collection with demotion (move to cold-storage list).
4. **Design a workload variant where utility rule has something to do.** Add a population of entities that keep edges but are never queried, so v0.1.1 can demonstrate value over v0.1.0.

After those four, re-run the Stage 2 baseline. If all four UC gates pass and v0.1.2 measurably beats v0.1.0 on store-reduction without losing entity recall, promote to Stage 3.

## Pointers

- Code: `experiments/gc_stage2_baseline.py`, `runner/gc_runner.py`, `runner/gc_variants/`
- Workload: `fixtures/workloads/w_graph_churn.py`
- Tests: `tests/test_gc_variants.py` (26 tests, all green)
- Opportunity scan: [`opportunity-graph-gc.md`](opportunity-graph-gc.md)
- Artifact: `runs/gc_stage2_baseline/20260607T181744.json`

## Reproduce

```sh
.venv/bin/python experiments/gc_stage2_baseline.py
# defaults: n_entities=50, n_facts=2000, fact_lifetime_days=7,
#           pin_fraction=0.10, query_fraction=0.15, seed=42
```
