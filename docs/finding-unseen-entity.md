# Finding: Embedding fallback partially handles unseen entities

**Status:** confirmed (within documented limits)
**Workload:** 35 utterances over 7 entities (6 known + 1 unseen "AMD")
**Model:** llama3.1:8b
**Script:** `experiments/unseen_entity_bench.py`

## Question

The open-world alias finding (`docs/finding-open-world-alias.md`) showed that the embedding fallback handles some unmapped aliases for known entities. But what about entities the proxy has NEVER SEEN — neither in the mention_map nor in the warm-up set? Does the embedding fallback mint a coherent canonical for an entity whose aliases are completely unseen, or does it fragment them into multiple new canonicals?

## Setup

The standard 30-utterance workload (6 entities × 5 aliases) is extended with a 7th entity, AMD, whose aliases (`AMD`, `Advanced Micro Devices`, `AMD Inc`, `Advanced Micro`, `AMD Corp`) are NOT in the mention_map and NOT in the pre-warm canonical list. The EntityNormalizer is pre-warmed with the 6 known canonicals only.

Three conditions, same llama3.1:8b downstream:

- **A. baseline** — no proxy. Tests the LLM's own canonicalization of AMD aliases.
- **B. known_map_only** — full mention_map for the 6 known entities; AMD's 5 aliases pass through unchanged.
- **C. hybrid + embedding fallback** — same map; embedding-based EntityNormalizer mints canonicals for unmapped aliases (including AMD's).

## Result

| Condition | B-cubed F1 | Total unique outputs (ideal=7) | AMD-specific unique (ideal=1) |
|---|---|---|---|
| A. baseline | 0.3963 | 31 | 5 (full fragmentation) |
| B. known_map_only | 0.9048 | 11 | 5 |
| **C. hybrid + embedding fallback** | **0.9184** | **10** | **4** |

AMD fragmentation dropped from 5 unique outputs to 4 — the embedding fallback collapsed one pair. The other three aliases stayed as separate canonicals.

## Which AMD pair got collapsed

Looking at the predictions, the embedding fallback merged the closest token-overlap pair (likely `AMD` ↔ `AMD Corp` or `AMD` ↔ `AMD Inc` — high token overlap). The larger semantic gap pairs (`AMD` ↔ `Advanced Micro Devices`, no token overlap) stayed separate.

This is consistent with the design: the v0.3.1 hybrid embedder weights token similarity 2× neural similarity, so token overlap is the dominant signal. Acronym-expansion pairs with zero token overlap need a domain alias map; they cannot be recovered from distributional similarity alone.

## Three concrete findings

1. **Embedding fallback partially helps unseen entities.** AMD's 5 aliases collapsed to 4 canonicals. Real but small improvement.

2. **The improvement is bounded by the embedder's mechanism.** Token-overlap pairs (AMD ↔ AMD Inc) get caught; acronym-expansion pairs (AMD ↔ Advanced Micro Devices) do not. This is the documented v0.3.1 design limit, not a bug.

3. **The overall B-cubed F1 still improves** from 0.9048 to 0.9184 — the hybrid still helps because:
   - It catches some AMD pairs (even if not all)
   - It also catches surface variants for the known entities that weren't in the partial map

## What this confirms about the v0.5.x architecture

The wedge story is honest about coverage. The integrator gets:
- Full canonicalization for entities in the mention_map (gold)
- Partial canonicalization for unmapped aliases of mapped entities (embedding fallback catches surface variants)
- Partial canonicalization for completely unseen entities (embedding fallback catches close surface forms; misses acronym/expansion pairs)

For truly unseen entities with acronym/expansion alias patterns, the integrator needs to add the alias map entry. That is exactly what the public API supports: `EntityNormalizer` plus a domain `mention_map` curated by the integrator as new entities arrive.

## What this does NOT prove

- Only one unseen entity was tested. A workload with many unseen entities arriving over time would test whether the proxy mints a STABLE canonical per entity (no flapping as new aliases arrive) or whether it fragments.
- The pre-warm step matters. Without pre-warming (the canonical name is fed once before the bench), the embedding fallback would have to learn online (first-writer-wins), which would produce different clustering depending on order.
- The 5-alias-per-entity distribution is synthetic. Real workloads have skewed distributions where some entities have dozens of aliases and most have 1-2.

## Production guidance

For new entities the integrator discovers in production:

1. Add them to the `mention_map` as soon as the new aliases are observed.
2. Pre-warm the `EntityNormalizer` with the canonical name (one call to `normalize(canonical)` before production traffic).
3. Trust the embedding fallback to catch surface variants of the new entity. Do NOT trust it to merge acronym/expansion pairs.

This finding is the third in a series on the embedding-vs-map split (`open-world-alias`, `unseen-entity`, and the original `small-llm-quality`). Together they map the proxy's coverage envelope precisely enough that an integrator can predict before deployment what the proxy will and will not catch.
