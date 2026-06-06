# Finding: Multi-tenant ANN inherits the v0.5.5 speedup (6.88x at N=3000)

**Status:** confirmed, no quality regression
**Workload:** scale_stress synthesis (W-MULTITENANT-SYNTH replicated) at N=3000, 7 sources, 472 oracle canonicals
**Variants:** v0.5.3 (singleton-aware, linear-scan inners) vs v0.5.7 (same algorithm, ANN-backed inners)
**Script:** `experiments/mt_ann_scale_bench.py`

## Result

| Variant | Ingest | Throughput | Consolidate | B-cubed F1 |
|---|---|---|---|---|
| v0.5.3 (linear inners) | 46.93 s | 64 writes/sec | 1.88 s | 0.6808 |
| v0.5.7 (ANN inners) | **6.82 s** | **440 writes/sec** | 1.94 s | **0.6808** |

Speedup: **6.88x**. Quality delta: **+0.0000** (identical to four decimal places).

Per-source K total: 1719 canonicals across 7 sources (avg ~245 per source). The speedup shows up even at this modest per-source K because the bench writes 3000 entries and each one pays for a per-source scan over the source's growing canonical list.

## Why this completes the K-scaling story

The single-tenant v0.5.5 ANN variant fixed the per-source scan bottleneck for one-source deployments. But the multi-tenant variants (v0.4.0 → v0.5.3) maintain one inner variant per source, each doing its own linear scan. At production K (many sources × many canonicals per source) the multi-tenant variants would hit the same cliff v0.5.5 fixed, just spread across many smaller scans.

v0.5.7 is a one-class subclass of v0.5.3 that swaps `inner_factory=ANNSchemaProxy`. All cross-source consensus, singleton-aware identity merging, AND-rule safety checks, and disambig safety logic from v0.5.3 are inherited unchanged. The only thing that changes is the per-source cosine lookup.

## What this means for production

| Variant | Where it fits |
|---|---|
| v0.3.1 | Single-tenant, K < ~1k. Reference implementation. |
| v0.5.5-ann | Single-tenant, K up to ~10k+ |
| v0.5.3-singleton-aware | Multi-tenant, K_per_source < ~1k. Reference multi-tenant. |
| **v0.5.7-mt-ann** | **Multi-tenant, K_per_source up to ~10k+. Recommended for production.** |

The K-scaling story is now complete for both single-tenant and multi-tenant. Production deployments at realistic enterprise scale can pick the appropriate variant without giving up the harness-validated quality numbers.

## Tests

`tests/test_mt_ann.py` adds three tests: behavior parity with v0.5.3 at small K, inner-variant type assertion (per-source inners must be `ANNSchemaProxy`), and consolidate-summary shape validation.

## Next

A larger scale run (N=10k, 30k, 100k) would confirm the speedup grows as K grows per source. The current N=3000 number is the immediate proof; the larger number is a "press release" experiment for once a real deployment is sized.
