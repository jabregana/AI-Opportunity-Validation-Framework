# Finding: Final F1 is Cadence-Invariant for Lazy Variants (Drift Type D)

Status: experimental, single-author sweep, June 2026.
Reproduce: appendix script in this doc.

## Question

Does the cadence at which `consolidate()` runs affect the final
clustering quality of lazy consensus variants? If yes, there is a
real operational dial with a quality cost. If no, deployment teams
can pick cadence purely on read-latency requirements.

## Setup

For each lazy variant, simulate periodic consolidation at different
cadences: every 1, 10, 50, 100, and N writes (where N is the workload
size; consolidate-once-at-end). Measure final per-item B-cubed F1
after the full workload has been ingested.

Sweep on both multi-tenant workloads.

## Results

### W-MULTITENANT-SYNTH (516 entries)

| Variant | cadence=1 | 10 | 50 | 100 | 516 (end-only) |
|---|---|---|---|---|---|
| embed-proxy-v0.4.2-lazy-consensus | 0.3258 | 0.3258 | 0.3258 | 0.3258 | 0.3258 |
| embed-proxy-v0.4.3-and-rule | 0.3258 | 0.3258 | 0.3258 | 0.3258 | 0.3258 |
| embed-proxy-v0.4.4-adaptive | 0.4750 | 0.4750 | 0.4750 | 0.4750 | 0.4750 |

### W-MULTITENANT-WIKIDATA (138 entries)

| Variant | cadence=1 | 10 | 50 | 138 (end-only) |
|---|---|---|---|---|
| embed-proxy-v0.4.2-lazy-consensus | 0.3873 | 0.3873 | 0.3873 | 0.3873 |
| embed-proxy-v0.4.4-adaptive | 0.3873 | 0.3873 | 0.3873 | 0.3873 |

## What this shows

**F1 is invariant to cadence across all tested cadences for all lazy
variants.** Whether you consolidate every single write or once at the
end of the workload, the final clustering quality is identical.

This is a property of how consolidate() is implemented: the merge
state is recomputed from scratch each call using the full accumulated
aliases and embeddings. The result depends only on the final state
of `self._aliases` and `self._embeddings`, not on the order in which
prior consolidations ran. Mathematically, the merge equivalence
classes that emerge are a function of the post-ingestion state
alone.

## Operational implication

Cadence is a pure read-latency-vs-stale-merge-cost trade-off, with no
final-quality penalty. Choose cadence based on:

- How fresh you need cross-source merges to be in real-time queries.
  Hourly consolidation means a sales write and an ops write can be
  unmerged for up to an hour. If that's acceptable, hourly is fine.

- Cost of running consolidate. O(K^2) in current implementation
  where K is the number of (source, local) cluster keys. Once per
  hour at K ≈ 10k is feasible; once per second is not. The exact
  cost depends on the embedder's centroid computation, which is
  also O(K * number_of_aliases_per_cluster).

- Read consistency requirements. If clients expect consistent
  canonicals across rapid reads from different sources, consolidate
  more often.

There is no quality argument for choosing a particular cadence.

## Caveat

The cadence-invariance result holds only because:

1. The inner variants (v0.3.1 hybrid + structural filter) are
   deterministic and cache results per-input. Two passes over the
   same input give identical canonicals.

2. The consolidate algorithm is itself deterministic given a fixed
   `self._aliases` and `self._embeddings` state.

3. The test does not measure intermediate states (only the final).
   Reads BETWEEN consolidations would see stale merge state; the
   `drift_rate` metric in UC-4.1 measures this. This sweep measures
   the steady-state quality, not the transient quality during
   ingestion.

If the inner variant were non-deterministic (e.g., used a stochastic
embedder), or if the consolidate algorithm were itself stochastic
(e.g., using random sampling), this invariance would not hold.

## Appendix: sweep reproducer

```python
from fixtures import workloads
from runner.variants import build
from runner.metrics import alignment

w = workloads.load("W-MULTITENANT-SYNTH")
oracle = [(e.input, e.oracle_canonical) for e in w]
for variant_id in ["embed-proxy-v0.4.2-lazy-consensus",
                   "embed-proxy-v0.4.3-and-rule",
                   "embed-proxy-v0.4.4-adaptive"]:
    for cadence in [1, 10, 50, 100, len(w)]:
        v = build(variant_id)
        for i, e in enumerate(w, 1):
            v.align_with_context(e.input, {"source_id": e.source_id})
            if i % cadence == 0 and hasattr(v, "consolidate"):
                v.consolidate()
        if i % cadence != 0 and hasattr(v, "consolidate"):
            v.consolidate()
        preds = [(e.input, v.align_with_context(e.input, {"source_id": e.source_id})) for e in w]
        bcubed = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
        print(f"{variant_id} cadence={cadence}: B-cubed={bcubed:.4f}")
```
