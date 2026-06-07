# Finding: On a shared-user store, Mem0's own deduplication absorbs much of the wrapper's value

**Status:** confirmed (with important nuance vs the earlier per-user-id result)
**Workload:** 30 simulated sessions (5 sessions × 6 entities, each session is a short 3-turn dialogue mentioning one entity via a different alias)
**Live system:** Mem0 v2.0.4 with Qdrant local vector store, llama3.1:8b as the LLM, all-minilm as the embedder
**Script:** `experiments/mem0_multi_session_bench.py`

## Question

The earlier live-Mem0 finding (`docs/finding-mem0-live-wrapper.md`) used 30 distinct `user_id` values — each session was its own user store. With the wrapper: Alphabet mentions went 0→3, Microsoft 1→5, Tesla 1→5 in the stored memory text. Big win at the content level.

But the realistic long-form conversational scenario is ONE user with many sessions over time, all accumulating in a single shared store. Does the wrapper's advantage persist when Mem0 has the opportunity to deduplicate across sessions?

## Setup

Same 30 sessions, same alias map, same model. Difference: **all 30 sessions ingest under one shared `user_id`** ("shared_user"). After ingestion, run a search query for each canonical entity name (top-10) and inspect which stored memories surface.

Two conditions:
- **no_wrapper:** raw Mem0
- **with_wrapper:** Mem0PreNormalized in front

## Result

| Metric | No wrapper | With wrapper |
|---|---|---|
| Total stored memories | 20 | 20 |
| Memories mentioning Alphabet | 4 | 4 |
| Memories mentioning Amazon | 2 | 2 |
| Memories mentioning Apple | 3 | 2 |
| Memories mentioning Microsoft | 4 | 2 |
| Memories mentioning Nvidia | 5 | 6 |
| Memories mentioning Tesla | 2 | 4 |
| Macro retrieval F1 (top-10 per canonical) | 0.523 | 0.510 |
| Ingest time (cache-warmed) | 89.4s | 87.6s |

The per-entity coverage in the store is similar with vs without wrapper. The dramatic 0→3 / 1→5 / 1→5 shift seen in the per-user-id bench does not reproduce on a shared store.

## Why the wrapper's advantage shrinks on a shared store

Mem0 v2's extraction layer has its own internal merge/dedup behavior. On a shared store with many sessions about the same entities, Mem0 itself collapses surface-form variation: even without the wrapper, the LLM extraction normalizes "AAPL" / "Apple" / "Apple Computer" into stored facts that lean on whatever surface form Mem0's LLM decides is canonical.

This is good and bad:
- **Good for the unwrapped case:** Mem0 isn't completely passive about surface form variance. It does some of the canonicalization the wrapper would do.
- **Bad for measuring wrapper lift:** the wrapper's "I substitute canonical names upstream" wins are partly absorbed by Mem0's downstream dedup. The deltas in stored coverage are no longer dramatic.

## So when does the wrapper add value?

Combining this finding with the earlier per-user-id bench:

- **Per-tenant deployments (each user has their own store):** the wrapper adds substantial value because Mem0 has no cross-session dedup signal within a user. Surface variation in inputs translates directly to surface variation in stored memories. Per-user-id bench: 0→3 / 1→5 / 1→5 mention counts.

- **Shared-store deployments (one user accumulates everything):** Mem0's own dedup absorbs the surface variation. The wrapper still pre-normalizes (no harm) but the gain in stored-content canonicality is smaller.

- **Retrieval-quality:** macro F1 was essentially flat (0.523 vs 0.510, within metric noise at this N). At this N=20 store size and with significant alias overlap across memories, the metric isn't sharp enough to detect a difference.

## The commercial implication

The wrapper's killer-app shape is **multi-tenant deployments** where each customer/user has their own per-tenant memory store. That's most B2B SaaS / agent platforms. The per-user-id finding directly applies:

- Customer support memory (per-customer ticket history)
- Agent platforms with isolated tenant memory (Mem0's typical deployment)
- Per-user assistant memory (each end user's personal assistant)

The shared-store scenario (one user, many sessions, accumulating shared memory) is where Mem0's own machinery does more of the work, and the wrapper's additive value is smaller.

## What this does NOT prove

- N=20 stored memories is small. At scale (10k-100k memories per store), Mem0's dedup may struggle more and the wrapper's value may rise again.
- The retrieval F1 metric used here is noisy because of alias overlap (one memory may mention multiple companies, getting counted for multiple queries). A cleaner version would use a workload where each memory is unambiguously about one entity.
- The Mem0 LLM used (llama3.1:8b) makes the dedup decisions. A different LLM (a smaller or larger one) may have different surface-form preferences and dedup behavior.
- Only one alias-density profile tested (5 aliases per entity, evenly distributed across 5 sessions). Skewed distributions (one common alias + many rare ones) may behave differently.

## Recommended follow-ups

1. **Scale the shared-store bench to 200+ sessions.** Does the wrapper's advantage emerge at larger N as Mem0's dedup hits limits?
2. **Per-tenant store ablation.** Run the same workload with K different user_ids (K=1, 5, 30) and plot the wrapper's lift vs K. Should monotonically increase as users get more isolated.
3. **Real query workload.** Instead of top-10-by-canonical, simulate realistic queries ("when did the user last buy AAPL", "which companies did the user mention this week") and measure answer accuracy.

## What this lands for the project narrative

The wrapper's value at the storage layer is conditional on the store organization:
- Per-tenant: large and direct.
- Shared: smaller, depends on Mem0's own dedup behavior.

The single-tweet bench (without Mem0 in the loop) shows the unconditional value of the wrapper: -38.8% surface variants, +59pp canonical-output rate. That's the pure proxy lift. Mem0 dedup is doing additional work on top.

The honest pitch: "If you deploy us in front of a per-tenant memory system, you get dramatic stored-content canonicalization (0→3, 1→5 in our pilot). If you deploy us in front of a shared store, Mem0 already does some of the work but the wrapper still helps and produces deterministic canonicals you can rely on for downstream queries."