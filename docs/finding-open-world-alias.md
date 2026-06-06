# Finding: Partial alias map recovers 87% of the full-map lift; embedding fallback adds +0.037

**Status:** confirmed
**Workload:** 30 utterances over 6 oracle entities (the small_llm_quality_bench workload), routed through llama3.1:8b
**Script:** `experiments/open_world_alias_bench.py`

## Question

Prior LLM benches (`docs/finding-small-llm-quality.md`, `docs/finding-conversational-llm.md`) used a fully-closed `mention_map` — every alias the LLM might see was in the map. Real deployments have **open-world aliases**: aliases the integrator did not know about, or new aliases that arrive after the map was authored. The v0.5.x claim is that the embedding-based `EntityNormalizer` handles those via the variant's embedding similarity. Does it?

## Setup

Same 30-utterance workload from the single-sentence bench. Same llama3.1:8b downstream. Four conditions:

- **A. baseline** — no proxy at all. LLM sees raw text.
- **B. full_map** — all 30 aliases in the `mention_map`. Gold upper bound.
- **C. partial_map** — only 2 of 5 aliases per entity in the map (12 of 30 aliases). The 18 unmapped aliases pass through unchanged.
- **D. hybrid** — partial_map for known aliases, embedding-based `EntityNormalizer.normalize()` as fallback for everything else. The EntityNormalizer is pre-warmed with the 6 canonical entity names before the bench starts.

## Result

| Condition | B-cubed F1 | unique outputs (ideal=6) | Δ vs A |
|---|---|---|---|
| A. baseline | 0.4067 | 26 | — |
| B. full map (gold) | **1.0000** | 6 | +0.5933 |
| C. partial map (2/5) | 0.9259 | 8 | +0.5192 |
| **D. hybrid (partial + embedding fallback)** | **0.9630** | **7** | **+0.5562** |

Hybrid recovers ~94% of the full-map lift while requiring only 40% of the aliases to be known up front.

## Three concrete findings

**1. Partial coverage already does most of the work.** Covering just 2 of 5 aliases per entity (12 of 30) recovers 87% of the full-map lift (+0.5192 of +0.5933). The 12 mapped aliases are the "high-frequency" ones (bare name + ticker). The 18 unmapped aliases are surface variants and historical names; for many of them the downstream LLM already does some canonicalization on its own, so the partial map doesn't lose much.

**2. Embedding fallback adds +0.0370 over partial map alone.** The hybrid condition catches some unmapped aliases via embedding cosine — particularly surface variants where token overlap is high (e.g., "Apple Inc." → "Apple Inc" via the v0.3.1 hybrid embedder's token component). Small but real, and it lands the result within 3.7 points of the full-map gold.

**3. Embedding fallback is NOT a complete substitute for explicit aliases.** Hybrid still trails full map by 0.0370. The fallback struggles when the embedding similarity gap is too large:
- Ticker / acronym pairs (`AAPL` ↔ `Apple Inc`): zero token overlap, weak semantic similarity. Falls below the v0.3.1 threshold of 0.8 → minted as a new canonical → fragmentation.
- Historical names (`Apple Computer` ↔ `Apple Inc`): partial overlap ("Apple") but not high enough hybrid cosine. May or may not merge depending on exact thresholds.

These are the cases where the static `mention_map` carries information the embedding cannot recover. The proxy's design is honest about this: the embedding path catches surface-form variants; the alias map catches everything else.

## Production guidance (what to write in the integrator docs)

The recommended deployment is **hybrid**: a domain-specific `mention_map` covering the high-frequency aliases the integrator knows about, plus the `EntityNormalizer` as fallback for everything else. Concretely:

```python
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized

# Pre-warm the normalizer with known canonicals.
norm = EntityNormalizer("embed-proxy-v0.3.1")
for canonical in KNOWN_CANONICALS:  # 6-10 most important entity names
    norm.normalize(canonical)

# Build the partial map (the obvious / common aliases).
partial_map = {
    "AAPL": "Apple Inc",
    "Apple": "Apple Inc",
    # ... 2-3 per entity is enough
}

m = Mem0PreNormalized(
    Memory(),
    norm,
    mention_map=partial_map,
    # Optional: NER preprocessor to extract unmapped entity spans for
    # the embedding fallback path. Without this, unmapped aliases stay
    # in the text unchanged.
    mention_extractor=my_ner_extractor,
)
```

A clean partial map of 2-3 aliases per entity gets 87% of the value with 40% of the work; adding the embedding fallback closes another 6% of the gap to the gold ceiling.

## What this does NOT prove

- The 18 "unmapped" aliases in this bench are still drawn from the same 6 entities; they don't test true unseen-entity aliases (where the canonical itself is new). For that scenario the EntityNormalizer would mint a fresh canonical for the unseen entity, which is correct behavior but not measured here.
- The workload's alias distribution (5 per entity, mix of ticker / bare / suffix / historical) is synthetic. Real deployments may have very different distributions. A ticker-heavy workload would benefit more from the static map; a surface-variant-heavy workload would benefit more from the embedding fallback.
- The pre-warming step (feeding canonicals to the normalizer before the bench) matters. Without it the normalizer learns canonicals online (first-writer-wins), which produces different clustering depending on input order.

## Next experiments worth running

1. **Sweep the partial-map ratio.** Run the bench with 1, 2, 3, 4 aliases per entity in the map. Plot the lift curve.
2. **Test on a workload with unseen entities.** Add a 7th entity whose aliases never appeared at warming. Does the embedding fallback mint a coherent new canonical for it?
3. **Compare without pre-warming.** Run hybrid with no canonicals fed up front; see how much the online learning hurts.
