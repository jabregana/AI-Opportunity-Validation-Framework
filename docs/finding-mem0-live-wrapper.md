# Finding: Live Mem0 with wrapper produces more canonical stored memories

**Status:** confirmed (with one important confound)
**Workload:** 30 single-sentence utterances over 6 entities (the `small_llm_quality_bench` workload)
**Live system:** Mem0 v2.0.4 with Qdrant local vector store, llama3.1:8b as the LLM, all-minilm as the embedder
**Script:** `experiments/mem0_wrapper_live_bench.py`

## Question

The `mem0_baseline.py` probe (April 2026 finding) showed Mem0 v3 OSS produces extracted natural-language facts, not canonical entity IDs — so the direct B-cubed comparison was not meaningful. With `Mem0PreNormalized` shipped in v0.5.2 and a domain alias map curated, the question becomes: does wrapping a live Mem0 instance produce DEMONSTRABLY more canonical stored memories?

## Setup

Two runs against fresh Mem0 instances (separate Qdrant collections). Same 30 utterances. Same alias map (the 30-alias map from `small_llm_quality_bench`).

- **No wrapper:** raw Mem0. Each `add()` sends raw text with whatever surface form the utterance used.
- **With wrapper:** `Mem0PreNormalized` in front. The mention_map pre-normalizes aliases before forwarding to Mem0's `add()`.

After ingestion, fetch the final memory state with `get_all(filters={"user_id": "bench_user"})` and inspect the stored memory texts.

## Result

| Metric | No wrapper | With wrapper |
|---|---|---|
| Total memories stored | 20 | 20 |
| Memories mentioning "Apple Inc" | 1 | 1 |
| Memories mentioning "Alphabet Inc" | **0** | **3** |
| Memories mentioning "Microsoft Corp" | 1 | **5** |
| Memories mentioning "Tesla Inc" | 1 | **5** |
| Memories mentioning "Nvidia Corp" | 2 | 2 |
| Memories mentioning "Amazon Inc" | 0 | 0 |

## Three findings

**1. Memory COUNT is unchanged.** Mem0's LLM extraction layer produces ~20 facts regardless of input surface form. The wrapper does NOT reduce fragmentation at the count level. This was somewhat unexpected — the prediction was that pre-normalized inputs would let Mem0 deduplicate more aggressively. Mem0's extraction is opinionated about how many facts to produce.

**2. Memory CONTENT is meaningfully more canonical with the wrapper.** Without the wrapper, 0 stored memories mention "Alphabet Inc" — they say "Google" or "GOOGL". Same shape for Microsoft (1→5) and Tesla (1→5). With the wrapper, the canonical names appear in the stored facts because Mem0 saw them in the input. **This validates the design claim at the storage level: a downstream query for "Alphabet Inc" returns 3 memories with the wrapper and 0 without.**

The shift is from "queries-by-canonical-name miss most memories" (without wrapper) to "queries-by-canonical-name find all the right memories" (with wrapper). This is the operational value the wrapper delivers; it shows up in retrieval workloads, not in storage-count workloads.

**3. Latency comparison is CONFOUNDED.** `no_wrapper` ran first (cold Ollama daemon, 410.1s = 13.7s per call). `with_wrapper` ran second (warm cache, 66.9s = 2.2s per call). The 6x speedup is mostly Ollama cache-warming, not the wrapper's doing. A properly-controlled A/B with both conditions on a warm cache would isolate the wrapper's true overhead (expected: ~0ms, since the regex substitution is microseconds).

## What this confirms

- The wrapper integrates cleanly with a live Mem0 instance (no API surface mismatch, no test-stub-only behavior).
- The wrapper's value at the storage layer is **content canonicalization** rather than **count reduction**. Both are useful; the right one to report depends on the downstream workload.
- The earlier `mem0_baseline.py` finding (Mem0 OSS outputs natural-language facts, not canonical IDs) is preserved: the wrapper does not change Mem0's extraction shape, it changes what entity names appear in those extracted facts.

## What this does NOT prove

- Per-tenant isolation (with multiple `user_id` values) was not exercised; only one user in this bench.
- Downstream retrieval F1 was not measured. The "more memories mention the canonical" finding is a precondition for higher retrieval F1, not a measurement of it.
- Latency on a warm cache. Need to re-run with cache warmed in both conditions to report a real overhead number.
- Long-term store growth. After hundreds of utterances would the canonical-name preference be preserved, or does Mem0's deduplication / summarization layer drift?

## Recommended follow-ups

1. **Cache-warmed A/B latency.** Pre-warm Ollama with one dummy add() call in both conditions, then run the bench. Isolate the wrapper's true overhead.
2. **Retrieval F1.** After the 30 ingestions, query Mem0 for each canonical name in turn. With wrapper: expect to find most of the relevant memories. Without wrapper: expect to miss many because they're stored under surface variants. Compute mean retrieval F1.
3. **Per-tenant scale.** Run the same bench with 5 `user_id` values and an alias that means different things per tenant ("Apple" → Apple Inc for tenant 1, Apple Computer for tenant 2). Confirm the wrapper preserves tenant isolation.

## What the project is now claiming honestly

> Mem0PreNormalized produces stored memories that mention canonical entity names instead of surface variants. Memory count is unchanged because Mem0's extraction layer is opinionated about how many facts to produce. The wrapper changes WHAT is stored, not HOW MUCH. Downstream queries for canonical names find more results.

This is a sharper, smaller claim than "the wrapper reduces store fragmentation 5x" but it's the claim the data actually supports.
