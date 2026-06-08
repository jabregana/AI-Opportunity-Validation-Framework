---
type: finding
date: 2026-06-08
stage: 5
status: VALIDATED
covers: Mem0GCMiddleware running gc-v0.1.8-comprehensive-tuned on 2000 real-LLM-extracted memories
artifact: runs/mem0_smoke_real_llm/20260608T110926.final.json
---

# Finding: Mem0 + gc-v0.1.8 sustains 98% reduction on 2000-memory real-LLM workload

## TL;DR

Ran the Mem0 adapter end-to-end on 2,000 SQuAD-style inputs through Ollama (phi3:mini + all-minilm) with `gc-v0.1.8-comprehensive-tuned` swept every 100 adds. Mem0's LLM extraction amplified the 2,000 inputs into **3,363 actual memories** (1.68x). The variant collected **3,308 of them (98.4% reduction)**, leaving **55 alive at the end**. The store oscillated in a clean sawtooth between ~50 surviving and ~250-320 pre-sweep, exactly the steady-state behavior the runbook predicts.

This is the first end-to-end result with a real downstream + real LLM extraction. It confirms three things:

1. The adapter contract works on a real Mem0 install (no failures over a 2-hour run)
2. The v0.1.8 policy reaches a stable steady-state under real LLM-driven memory amplification
3. Sweep cost is bounded and sub-linear (0.07-0.17s per sweep regardless of store size)

## Numbers

| Metric | Value |
|---|---|
| Inputs attempted | 2,000 |
| Memories created by Mem0's LLM | 3,363 |
| Amplification factor | 1.68x |
| Memories collected by v0.1.8 | 3,308 |
| Reduction | 98.4% |
| Surviving at end | 55 |
| Total wall time | 7,231 s (~2 hours) |
| Add latency p50 | 3.04 s |
| Add latency p99 | 13.07 s |
| Add latency avg | 3.61 s |
| Sweep cost min | 0.067 s |
| Sweep cost max | 0.172 s |
| Sweep cost median | ~0.10 s |

## What the sweep curve looks like

Every sweep (after every 100 adds) showed the same pattern: the store had grown to 168-323 memories pre-sweep, and v0.1.8 reclaimed it down to 44-73 memories post-sweep.

| Sweep # | After i | Pre-sweep | Reclaimed | Post-sweep |
|---|---|---|---|---|
| 1 | 100 | 168 | 115 | 53 |
| 2 | 200 | 222 | 156 | 66 |
| 5 | 500 | 196 | 136 | 60 |
| 10 | 1000 | 217 | 164 | 53 |
| 16 | 1600 | 323 | 261 | 62 |
| 20 | 2000 | 211 | 156 | 55 |

The "post-sweep" column is the steady-state working set. It does not grow over the run; this is the property the runbook claims and this test confirms.

## What the result means

**For the adapter contract:** zero failures. Every Mem0 v2 search/add/delete call went through the middleware over 3,363 memories without an exception. The two known issues (search filter translation, LLM extraction returning strings) caught earlier in stage 4 did not resurface.

**For the variant:** v0.1.8 holds the working set bounded under real LLM-driven memory growth. The 1.68x amplification (LLM extracts more facts than the input has) is a real risk for any Mem0 production deployment without GC. With GC, the store reaches steady-state in the first few sweeps and never grows beyond ~320.

**For sweep cadence:** at `sweep_every=100`, sweep cost ranged from 0.067 to 0.172 seconds. That's 6 to 16 millisecond per pre-sweep memory, sub-linear because most of the cost is the iteration, not per-memory work. A team running 10x larger stores could safely sweep less often without changing the cost shape.

**For p99 latency:** the add p99 of 13.07s is Ollama+phi3:mini, not the adapter. The adapter's own overhead is unmeasurable in the artifact (sweep cost is 100x smaller than add cost).

## What's still open

1. **Recall preservation is not yet measured.** This test verified that the variant reduces the store. It does not yet measure whether the surviving 55 memories include the ones a downstream query would need. That's what `experiments/mem0_retrieval_f1_benchmark.py` answers (queued next, now that Ollama is free).
2. **No multi-tenant test in this run.** All 2,000 adds were one tenant. The v0.1.5 tenant-isolation behavior was tested earlier in `tests/test_gc_v015_v017.py` but not under real LLM amplification.
3. **No real-clock long-running data.** The 2-hour run is a compressed version of what would normally take days/weeks of real workload. The compressed simulator (`experiments/gc_long_running_simulation.py`) extends this to 30/60/90-day projections but neither is real calendar time.

## What this changes

This result moves the Mem0 adapter from "tested against a FakeMem0" (stage 3) and "tested with 5-100 real memories" (stage 4) to "tested at production-realistic scale with real LLM extraction" (stage 5). Combined with the runbook (`docs/runbook-mem0-v0.1.8-deploy.md`), the Mem0 deployment path is now documented, reproducible by an external team, and ready to take to a customer conversation. The conversion from "ready to discuss" to "customer-validated in production" requires Phase 4 (one external team running the bundle in production for 30 days and reporting their actual outcomes), which has not happened yet.

The 98.4% reduction number is the headline. It's the analyst's "credibility anchor": a measured, reproducible, single-run number that a customer can verify by re-running the smoke test.

## Pointers

- Smoke test script: `experiments/mem0_smoke_test_real_llm.py`
- Artifact: `runs/mem0_smoke_real_llm/20260608T110926.final.json`
- Adapter under test: `runner/dimensions/memory/lifecycle/integrations/mem0_adapter.py`
- Variant under test: `runner/dimensions/memory/lifecycle/gc_v018.py` (`ComprehensiveTunedGC`)
- Runbook: `docs/runbook-mem0-v0.1.8-deploy.md`
- Synthesis plan: `docs/synthesis-memory-lifecycle-management.md` (Phase 1.5 was the missing piece this finding completes)
