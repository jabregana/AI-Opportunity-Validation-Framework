# Finding: Inner Variant's Per-Write Cost is O(K), Catastrophic at K=16k

Status: experimental, June 2026.
Reproduce: `experiments/scale_stress.py --scale 100000`.

## Question

The UC-4.6 latency benchmark measured p99 ~28ms at K ≈ 300 canonicals. Does that latency hold at production scale (K = 10k, 100k, or more)?

## Setup

Synthesized multi-tenant workloads at 10k and 100k entries by replicating the W-MULTITENANT-SYNTH base with input suffix variations. Same 7 sources; canonical count grows with the workload.

Ran v0.4.4 adaptive ingestion plus single end-of-workload `consolidate()`. Measured ingestion total time, consolidate time, query pass time, B-cubed F1, and process memory delta.

## Results

| Scale | Canonicals K | Ingest time | Ingest writes/sec | Consolidate time | Final F1 | Memory delta |
|---|---|---|---|---|---|---|
| 516 (SYNTH base) | ~80 | 4s | 130/sec | ~0.5s | 0.475 | ~150 MB |
| 10000 | 1616 | 72s | 139/sec | 1.8s | 0.717 | 1.8 GB |
| **100000** | **16262** | **6196s (1h 43min)** | **16/sec** | **120.6s** | **0.746** | **8.6 GB** |

**Ingestion throughput collapses from 139 writes/sec at K=1600 to 16 writes/sec at K=16k.** A ~9x throughput drop for a 10x increase in canonicals. This is consistent with O(K) per-write cost in the inner variant.

## Why

Each `align_with_context(input)` call does:
1. Embed the input (constant cost, ~5ms for the hybrid embedder)
2. Cosine search across ALL existing canonicals (O(K) for K canonicals in that source's inner variant)

The cosine search dominates as K grows. At K=16k:
- 16k cosine computations per write, each ~512-dim
- ~80M floating-point operations per write
- Pure Python (no SIMD, no batching) makes this ~50ms per write
- Plus embedding cost: ~5ms
- Total ~55-60ms per write at K=16k

Multiplied by 100k writes: 5500-6000 seconds. Matches the observed 6196s.

## Implication

The earlier UC-4.6 latency claim ("p99 27ms at single thread") is only valid at the K under which it was measured (~300 canonicals). Production deployments with K in the thousands to millions need:

1. **Approximate nearest neighbor index** (FAISS, Annoy, ScaNN) for the inner variant's similarity search. Cuts O(K) to O(log K) or O(sqrt K).
2. **Batched embedding** if writes can be queued briefly. Amortizes embedding cost.
3. **Sharded canonical store** by source or by some bucket key. Each shard stays small.

None of these are in the current implementation. The harness's pure-Python brute-force cosine was fine for evaluation at K ≈ 300 but does not scale to production.

## Cadence invariance at scale

Tested cadence=1 vs cadence=end at K=10k earlier (different commit). Result: identical B-cubed F1 = 0.7173 at both cadences. The earlier cadence-invariance finding **generalizes to K=10k** (a 65x scale-up from the original 138-516 entry tests).

The 100k run was end-only cadence (the per-write cadence at K=16k would have been impractical because of the O(K) inner cost). The invariance claim at K=100k is not directly tested but extrapolates from the K=10k confirmation.

## Updated wedge thesis caveat

The wedge thesis (the proxy is deterministic and faster than LLM-in-loop) is true at the K we tested. At production K (16k+), the inner variant's per-write cost becomes the bottleneck, and the gap between us and an LLM-in-loop approach narrows or flips:

- LLM-in-loop at K=16k: still ~1-3 seconds per write (LLM latency dominates, independent of K)
- Our v0.4.4 at K=16k: ~60ms per write
- Still ~20-50x faster, but the gap is smaller than at K=300 (where it was ~30-100x faster)
- At K=1M: LLM-in-loop still ~1-3s; ours would be ~3-5 seconds (with current brute-force search). Gap CLOSES or FLIPS.

The wedge thesis holds at typical agent memory scales (thousands of canonicals per source). It needs an ANN index to hold at very large scales (hundreds of thousands of canonicals per source). The ANN index work is a v0.5.x track and a real production prerequisite.

## Appendix: reproducer

```sh
# Warmup at 10k (~1 minute)
.venv/bin/python experiments/scale_stress.py --scale 10000

# Full run at 100k (~1.5-2 hours)
.venv/bin/python experiments/scale_stress.py --scale 100000

# Output written to runs/scale_stress_<timestamp>.json with the full
# per-phase timing breakdown.
```
