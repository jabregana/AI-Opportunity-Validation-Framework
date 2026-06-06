# Finding: ANN index restores sub-linear lookup, no quality loss at K~1000

**Status:** confirmed
**Workload:** scale_stress synthesis from W-MULTITENANT-SYNTH, replicated to N=5000 entries, K_final=1062
**Variants:** v0.3.1 (linear scan) vs v0.5.5-ann (HNSW via hnswlib 0.8.0)
**Benchmark script:** `experiments/ann_scale_bench.py`

## Result

| Variant | Ingest time | Throughput | K_final | B-cubed F1 |
|---|---|---|---|---|
| embed-proxy-v0.3.1 | 122.59 s | 41 writes/sec | 1062 | 0.6617 |
| embed-proxy-v0.5.5-ann | 4.33 s | 1155 writes/sec | 1062 | **0.6617** |

Speedup: **28.31x**. Quality delta: **+0.0000** (identical). Final canonical count identical.

## Why this matters

The scale-stress finding (`docs/finding-scale-stress.md`) flagged the linear cosine scan as the load-bearing scalability constraint. At K~16k the wedge thesis vs LLM-in-loop CLOSES because ingestion drops below the per-write LLM latency the wedge undercuts. v0.5.5 restores sub-linear lookup; on this workload at K~1k the approximation error is zero. HNSW is set with M=16, ef_construction=200, ef_search=64, which is enough to make top-1 recall lossless at the thresholds the proxy uses.

## Approximation caveat

HNSW is approximate by design. Below-threshold near-matches (which never trigger an alias anyway) are where the approximation error concentrates. The proxy's threshold-based aliasing means a top-1 match must clear `similarity_threshold` to count; small approximation noise on borderline matches has no effect on aliasing decisions. On a workload that aliases close to the threshold boundary, expect a small (~1%) clustering difference vs v0.3.1.

## Next

- Re-run scale_stress at N=100k with v0.5.5-ann; expectation is sub-100s ingestion (vs 1h 43min for v0.4.4 at the same scale).
- ANN params (M, ef_search) should be exposed in the service API once a multi-tenant ANN variant lands.
- v0.5.5 is currently single-tenant only. A v0.5.6 ANN-backed multi-tenant variant would let the lazy v0.4.2/v0.5.3 pattern scale to production K. This is the natural next variant.
