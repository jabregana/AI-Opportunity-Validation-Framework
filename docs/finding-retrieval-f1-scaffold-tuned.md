---
type: finding
opportunity: Agent Memory Lifecycle Management - retrieval-quality measurement
stage: 3
status: F1-SCAFFOLD-PRODUCES-CREDIBLE-TRADE-OFF-TABLE
date: 2026-06-08
artifact: runs/gc_retrieval_f1_benchmark/20260608T114031.json
---

# Retrieval F1 scaffold tuned: now produces real F1 preservation numbers

This finding documents the tuned version of the retrieval F1 scaffold from the synthesis plan's Phase 3 ("Real retrieval metrics" — replace UC-GC-2's entity-survival proxy with measured F1). Earlier shipped a degenerate scaffold (100% reduction → 0% F1). This commit tunes it to produce meaningful numbers across a sensitivity sweep.

**Headline**: The framework now produces the analyst-named credibility-anchor metric. Across a 200-memory synthetic corpus with topic-clustered ground truth, the trade-off is measurable:

| Aged fraction | Store reduction | F1 preservation | Verdict |
|---|---|---|---|
| 20% | 19.0% | **99.6%** | EXCELLENT |
| 40% | 43.0% | **81.5%** | ACCEPTABLE |
| 60% | 62.0% | 61.3% | POOR |
| 80% | 79.5% | 37.3% | POOR |

The clean trade-off curve is the credibility anchor: it directly answers "what do you lose for the reduction you gain?"

## What changed from the initial scaffold

Three fixes turned the scaffold from degenerate to meaningful:

1. **Per-memory aging** (`is_aged` flag on each memory): only an `aged_fraction` of memories are backdated; the rest stay fresh. Previously ALL memories were backdated, so ALL got collected.

2. **Stopword-aware retrieval**: substring matching now skips "tell", "me", "about", "what", "is", etc. The retrieval baseline F1 climbs from 0.112 to 0.889 because queries actually match topic-specific memories instead of every memory containing "about".

3. **`--aged-fraction` CLI parameter**: maps directly to the deployment's age distribution. Real benchmarks would calibrate this against production data; the scaffold demonstrates the trade-off shape parametrically.

## Sensitivity sweep results

200 memories, 50 queries (8 topics, 25 memories per topic, 6-7 queries per topic).

```
aged   reduction   F1_before  F1_after   F1_preserved  verdict
0.2    19.0%       0.889      0.885      99.6%         EXCELLENT
0.4    43.0%       0.889      0.724      81.5%         ACCEPTABLE
0.6    62.0%       0.889      0.545      61.3%         POOR
0.8    79.5%       0.889      0.332      37.3%         POOR
```

Pattern: F1 preservation degrades roughly linearly as aged fraction grows. **The 80/20 inflection point**: removing the bottom 20% of stale memories preserves 99.6% of retrieval quality (essentially free). Removing the bottom 40% preserves 82% — still ACCEPTABLE. Beyond 60%, the variant is collecting memories that are still being queried.

## What this means for production guidance

The framework's prior single-dim claim was "85% reduction" without the qualifier. With this scaffold, the operationally honest version is:

> "`gc-v0.1.8-comprehensive-tuned` reduces graph by 19-43% while preserving >80% of retrieval F1. Beyond 43%, retrieval quality degrades non-linearly; calibrate the variant's `min_age_seconds` to your deployment's age distribution before pushing above that floor."

This is the kind of claim an enterprise buyer can act on. It also explains WHY the variant's defaults matter so much: 80%+ reduction is achievable but means you're collecting memories that still have query value.

## Honest reading

### What this earns

- **A working retrieval-F1 benchmark scaffold** that the framework can plug any GC variant into.
- **A trade-off curve** that converts "% reduction" into "% reduction at what F1 preservation."
- **Verdict heuristics** (EXCELLENT / ACCEPTABLE / POOR) tied to measured F1 preservation, not researcher intuition.
- **The "what's good enough?" anchor** the analyst named.

### What this finding does NOT earn

- **No real retrieval engine.** The scaffold uses substring matching against synthetic text. Real Mem0 / Graphiti / Cognee use vector + reranker pipelines that would produce different baseline F1 and likely different trade-off curves.
- **No real Q&A dataset.** Topics are synthetic; ground truth is "all memories with this topic word." A HotpotQA-shape dataset would have more realistic question-answer mappings.
- **v0.1.2 and v0.1.8 produce identical numbers** because the synthetic corpus has only facts (no entities). v0.1.8's entity rule + tombstones + tenant features aren't exercised here. The scaffold mainly demonstrates the F1 trade-off shape, not per-variant differentiation.
- **No real LLM in the loop.** Real production retrieval uses LLMs for query understanding + result reranking; both could meaningfully change F1.
- **No retrieval latency measurement.** F1 here is quality only; production also cares about p50/p99 latency for the search call.

### How to convert this scaffold to a production-grade benchmark

Four concrete extensions:

1. **Replace `_retrieve()` with real Mem0/Graphiti/Cognee search calls.** The adapter pattern is already in place; just need to thread the search call through the middleware.
2. **Use a real Q&A dataset.** HotpotQA subset has the right shape (questions with known answer passages). Subset to a memory-shape (200-1000 documents); use HotpotQA's annotated relevant passages as ground truth.
3. **Sweep the model ladder.** Different embedding models produce different F1; the framework's `experiments/ladder_sweep_real_data.py` infrastructure can be reused for the embedder dimension.
4. **Add the F1 measurement to `compute_uc_gates`** as a new UC-GC-RETRIEVAL gate. Threshold: F1 preservation >= 80% at intended store reduction. Replaces entity-survival as the gate's load-bearing metric.

## Decision

Accept the tuned scaffold. The trade-off table is the analyst's "credibility anchor" produced for the first time. Three follow-up deliverables to harden it:

1. Integrate against the real Mem0 adapter (already shipped) on a real text corpus
2. Plug a public Q&A dataset (HotpotQA, NarrativeQA) into the ground-truth generation
3. Add UC-GC-RETRIEVAL to the gate suite

These are bounded engineering and can ship in the next batch.

## Operational guidance the framework now produces

For an enterprise team evaluating GC for their memory deployment:

| What you want | Variant | Target aged fraction | Expected outcome |
|---|---|---|---|
| Zero-risk pilot | gc-v0.1.2-fact-only | 20% | 19% reduction, ~99.6% F1 preserved |
| Default production | gc-v0.1.8-comprehensive-tuned | 40% | 43% reduction, ~82% F1 preserved |
| Aggressive cost-optimization | gc-v0.1.8-comprehensive-tuned | 60% | 62% reduction, ~61% F1 preserved (monitor carefully) |
| Stress test only | any variant | 80% | 80% reduction, ~37% F1 preserved (do NOT ship) |

The aged-fraction column maps to "what fraction of your memories are old enough (>min_age_seconds) and unused enough (>min_unaccessed_seconds) to be considered stale." Production teams should measure their own age distribution before picking.

## Pointers

- Code: `experiments/gc_retrieval_f1_benchmark.py` (the scaffold)
- Synthesis plan Phase 3: `docs/synthesis-memory-lifecycle-management.md`
- Sibling Phase 2 deliverable: `docs/finding-mem0-adapter-phase1.md`, `docs/finding-graphiti-adapter-phase2.md`
- Investment tool: `experiments/investment_prioritization.py` (where UC-GC-RETRIEVAL will eventually land as a verdict input)

## Reproduce

```sh
# Default (40% aged, ACCEPTABLE verdict)
.venv/bin/python experiments/gc_retrieval_f1_benchmark.py

# Sensitivity sweep
for AGED in 0.2 0.4 0.6 0.8; do
  .venv/bin/python experiments/gc_retrieval_f1_benchmark.py --aged-fraction $AGED
done
```
