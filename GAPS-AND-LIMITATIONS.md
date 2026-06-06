# Gaps and Limitations

This document is a candid audit of what the current state of the project does and does not prove. Written so an outside reader can decide for themselves where the claims hold and where they need more work.

## Are we pressure-testing conclusively? No.

Here is what we have versus what we would need for production-credible claims.

| Dimension | What we have | What we would need | Status |
|---|---|---|---|
| Single-tenant clustering | WikiData 2457 entries, real paraphrase distribution, paired bootstrap with tight CIs | Same plus a second real corpus | Decent |
| Single-tenant Tier B safety | WikiData 70 hard-negative pairs, machine-mined | Thousands of pairs, hand-validated | Thin coverage |
| Latency | Single-thread p99 on 2457 writes | QPS sweeps under concurrent load, longer runs to surface tail behavior | Floor only |
| Multi-tenant clustering | Two workloads totaling 654 entries (516 synthetic + 138 KG-grounded) | Real multi-team agent logs at thousands of entries | Weak |
| Multi-tenant Tier B | None | Cross-source false-merge fixture | Missing |
| Real agent memory ingestion | Zero | LongMemEval-S or equivalent fully integrated | Missing |
| Downstream task evaluation | UC-4.7 lite (held out from the same workload) | Retrieval F1 from a real QA task with the proxy interposed | Missing |
| Scale | K (canonical count) ≈ 300 maximum | K = 10k-1M to surface O(K^2) consolidate cost and memory profile | Missing |
| Production noise patterns | Three coarse noise modes at fixed rates | Domain shift over time, mixed-language inputs, Levenshtein-close typos, adversarial users | Thin |
| Direct comparison against Mem0 | None | Run Mem0 v3 on the same workloads, compare F1 and latency | Missing |

### The specific holes that bite hardest

1. **The whole multi-tenant story rests on two small synthetic workloads we authored.** The synthetic workload was built around the strata the variants would need to navigate, then victory was declared when v0.4.4 navigated them. That is the textbook selection-effect problem. The "v0.4.4 passes both workloads" claim is real but its generalization to production is unproven.

2. **Cadence invariance is a small-K artifact.** The finding that "cadence does not affect final F1" holds on 138-516 entry workloads. At K=10k+, ordering effects in union-find and floating-point centroid drift might break this. We do not know.

3. **No comparison against Mem0 v3.** The wedge thesis is "we beat LLM-in-loop." We have never run Mem0 v3 on the same data to verify. The latency claim (30ms vs 500-2000ms) is from typical LLM API numbers, not measured against an actual Mem0 deployment. A reviewer would correctly ask "show me your variant beating Mem0 on Mem0's own benchmark."

4. **UC-4.7 lite is held out from the same workload.** Real UC-4.7 is held-out questions against a different memory ingestion. The "held-out generalization 28% on WikiData" number is an in-distribution test, not true generalization.

5. **Tier B at 70 pairs is thin.** v0.3.1 passed WikiData Tier B at 0/70. That tells us we do not fail on those 70 specific pairs. Production has thousands of edge cases. 70 is a vibe check, not a proof.

## Where we fall short of the wedge ambition

The original thesis from `docs/opportunity.md`:

> A deterministic, no-LLM-in-hot-path schema-alignment proxy that out-competes Mem0's LLM-in-extraction-prompt approach on agent memory graphs.

Six things we would need to claim this credibly. Status of each:

| Claim | Status |
|---|---|
| Deterministic write path | Done |
| No LLM in hot path | Done |
| Lower latency than LLM approach | 30ms p99 measured, but vs Mem0-typical numbers, not vs measured Mem0 |
| Comparable or better clustering quality than Mem0 on real data | Unverified. Never run Mem0 on the same workloads. |
| Works on real agent memory (multi-turn dialogue, real entities) | Unverified. LongMemEval stubbed. Synthetic only. |
| Production-ready at scale | Unverified. K ≈ 300 maximum tested. No memory profile, no concurrent-write test. |

So we have a credible PROTOTYPE with a defensible measurement harness. We do not have a verified PRODUCT.

## What would actually move the project from prototype to claim-defensible

In order of payoff per session of effort:

1. **Run Mem0 v3 on W-WIKIDATA-PROPS.** Use the Mem0 SDK, ingest the same workload, query the canonicals it produces, score with the same B-cubed F1 metric. If v0.3.1 beats it, that is a defensible head-to-head. If not, the wedge thesis needs revision. Single most important missing experiment.

2. **Real UC-4.7 with LongMemEval-S.** Build the NER + retrieval scorer. The current UC-4.7 lite is in-distribution; real UC-4.7 measures actual downstream impact. Two synth workloads plus one real benchmark turns a portfolio piece into a defensible artifact.

3. **Scale stress test.** Synthesize a 100k-entry workload (could just be 100x the existing synth) and run v0.4.4. Measure consolidate latency, memory consumption, whether cadence invariance survives. Surfaces operational ceilings before they bite in production.

4. **Multi-tenant Tier B fixture.** Same idea as the existing Tier B but cross-source: pairs where sales' and ops' canonicals should NOT merge despite surface similarity. Tests v0.4.x more rigorously than the workload metric alone.

5. **A second real multi-tenant dataset.** Not synthetic. Maybe Slack open-source data with channel as source_id, or Stack Overflow with tag as source_id. Removes the selection-effect concern.

Items 1 and 2 alone would change the project's status from "well-instrumented prototype" to "defensible technical artifact."

## Results from running items 1-5 (added 2026-06-06)

After this audit was first written, items 1-5 were attempted in one session. Results updated the picture substantially:

- **Item 1 (Mem0 head-to-head):** Not possible as designed. Mem0 v3 OSS produces extracted natural-language facts ("User mentioned X as Y"), not canonical entity IDs. The two systems address different problems. See `docs/finding-mem0-comparison.md`.

- **Item 2 (Real UC-4.7 with LongMemEval):** Adapted the dataset for clustering eval (question and answer as two entries that should cluster together). **All variants regressed against b-raw with statistical significance (p=1.0000, BLOCK_PR).** The proxies' algorithms (token overlap, short-text embedding) do not generalize to clustering long-form conversational text. See `docs/finding-longmemeval-regression.md`. This narrows the project's claim from "agent memory" broadly to specifically "schema alignment for entity and relation names in property graphs."

- **Items 3, 4, 5:** See following commits.

The LongMemEval regression is the most important new finding. It bounds the wedge thesis to short-text canonicalization rather than agent memory in general. The harness, the variants, and the workload findings within the narrowed scope are intact.
