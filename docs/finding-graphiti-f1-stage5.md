---
type: finding
date: 2026-06-09
stage: 5
status: ARCHITECTURAL-LIMITATION-OF-V0.1.X-SURFACED
covers: GraphitiGCMiddleware + v0.1.x variants; surfaces the orphan-node assumption baked into the entire v0.1.x family
artifacts:
  - runs/graphiti_retrieval_f1/20260608T214405.json (v0.1.8, backdate=10d, aged=0.4)
  - runs/graphiti_retrieval_f1/20260609T081056.json (v0.1.8, backdate=90d, aged=0.6)
  - runs/graphiti_retrieval_f1/20260609T094855.json (v0.1.2, backdate=10d, aged=0.4)
---

# Finding: v0.1.x variant family assumes orphan nodes; never triggers collection on Graphiti's edge-rich graph

## TL;DR

Three end-to-end Graphiti F1 benchmark runs on real Graphiti (Ollama phi3:mini + all-minilm + Neo4j) across three different test scenarios. **All three produced 0% store reduction**, including v0.1.2-fact-only which has the simplest possible collection rule.

| Run | Variant | Backdate | Aged frac | Records | Backdated | Swept | Reduction | F1 before | F1 after |
|---|---|---|---|---|---|---|---|---|---|
| 1 (original) | gc-v0.1.8-comprehensive-tuned | 10 days | 0.4 | 78 | 59 | 0 | **0%** | 0.269 | 0.269 |
| 2 (aggressive) | gc-v0.1.8-comprehensive-tuned | 90 days | 0.6 | 56 | 69 | 0 | **0%** | 0.299 | 0.299 |
| 3 (fact-only) | gc-v0.1.2-fact-only | 10 days | 0.4 | 58 | 37 | 0 | **0%** | 0.479 | 0.479 |

The UC-GC-RETRIEVAL gate technically PASSED in all three (100% F1 preservation at 0% reduction). The meaningful finding is that **the v0.1.x variant family has an architectural assumption that holds in flat-memory frameworks (Mem0) but never holds in graph-native frameworks (Graphiti, probably Cognee).**

This is the second time the framework has caught itself surfacing a real limitation. First was the entity-norm Stage 3→4 ranking flip. This is the second.

## The architectural finding

Every v0.1.x variant ultimately calls `should_collect()` with the rule:

```
in_degree == 0 AND age >= min_age_seconds [AND additional conditions for entity rule]
```

The `in_degree == 0` check is the "node is orphaned, nothing references it" gate. In Mem0 v2's flat memory model, every memory is an orphan by definition (Mem0 stores facts as independent records with no inter-memory edges). So the in_degree check is automatically satisfied, and the rest of the rule (age + tenant + entity gates) does the actual work.

In Graphiti, entities are connected by edges (MENTIONS, RELATES_TO, etc.). Episodes are connected to extracted entities. After even a single `add_episode` call, every node in the graph has at least one edge. The `in_degree == 0` gate is essentially never satisfied. The variant correctly returns `should_collect = False` for every record.

The variant family was designed and gate-tested on synthetic workloads (`fixtures/workloads/w_graph_churn.py`) that include explicit "edge removal" events. Those events drop a fact's last incoming edge, which makes the fact an orphan, which makes the fact eligible for collection. **In real Graphiti, no event ever removes an edge** (Graphiti's design is append-only; nodes are deactivated via validity timestamps, not edge removal).

## Three runs, three views of the same finding

### Run 1: v0.1.8, 10-day backdate, 0.4 aged

This was the original parallel-to-Mem0 attempt. v0.1.8 returns 0% reduction. Hypothesis at the time: the entity rule's 60-day-unaccessed gate isn't satisfied by a 10-day backdate. Defensible explanation.

### Run 2: v0.1.8, 90-day backdate, 0.6 aged

Aggressive scenario designed to trigger the entity rule (90d > 60d entity-unaccessed threshold; 60% aged > 40% original). v0.1.8 STILL returns 0% reduction. The entity-rule hypothesis is now refuted; something else is blocking collection.

### Run 3: v0.1.2, 10-day backdate, 0.4 aged

Bypasses the entity rule entirely. v0.1.2's only rule is `in_degree == 0 AND age >= 1 day`. Returns 0% reduction. **This is the smoking gun.** The blocking factor isn't the entity rule, isn't the tenant rule, isn't the tombstone rule. It's the `in_degree == 0` check that all v0.1.x variants share.

The framework's discipline of running multiple test scenarios is what made this diagnosis possible. Each run individually was "the variant returned 0%, that's odd." Three runs together cornered the cause.

## What this means for the framework's claims

### What still stands

- **Mem0 + v0.1.8 numbers**: 98.4% reduction (2000-input smoke), 81.6%/81.8% F1 preservation (n=50/200). Mem0 is a flat-memory framework. The in_degree assumption holds. These numbers are valid and reproducible.
- **The three adapters**: Mem0, Graphiti, Cognee adapters all conform to the GCIntegrationShim contract. They route reads/writes/deletes through the variant pipeline correctly. The adapter layer works.
- **The framework's gate machinery**: UC-GC-RETRIEVAL correctly returned PASS for all three runs (the runs technically preserved F1 because nothing changed). The framework didn't lie; it reported exactly what happened.
- **The Stage 5 documentation discipline**: this finding doc itself is the kind of artifact that gives the framework its credibility. Three runs, honest table, no spin.

### What needs caveating

| Prior claim | Updated claim |
|---|---|
| "v0.1.8 works across Mem0, Graphiti, Cognee" (implied by cross-adapter consistency tests) | "v0.1.8 works across Mem0 with measured 98.4% reduction. On Graphiti, v0.1.x produces SAFE NO-OP (0% reduction, 100% F1) because the in_degree==0 check never triggers in edge-rich graphs. Same expected for Cognee." |
| "Cross-adapter consistency tests prove the variant composes with all three adapters" | "Cross-adapter consistency tests prove the adapter contract is uniform. They do NOT prove the variant produces equivalent collection behavior across frameworks; it does not." |
| "The memory lifecycle bundle is production-shape for any of three downstreams" | "Production-shape for Mem0 (or any flat-memory framework). For Graphiti and Cognee, a new variant family (v0.2.x) is needed that operates on graph topology rather than orphan-node assumption." |

### What would fix this (v0.2.x design sketch)

The v0.1.x rules assume the "death moment" of a fact is "when its last incoming edge is removed." A graph-native v0.2.x variant family would need different death-moment heuristics. Three candidates:

1. **Subgraph-orphan rule**: collect a node when the connected subgraph it belongs to has had no queries in N days. Requires the adapter to track per-subgraph query timestamps.
2. **Validity-window rule**: respect Graphiti's `valid_at` / `invalid_at` timestamps directly. Collect nodes whose validity window expired N days ago and have no incoming edges from currently-valid nodes.
3. **Edge-weight decay rule**: edges get a weight that decays with time-since-traversed. Collect nodes whose strongest incoming edge weight falls below threshold.

Each is a real research question, not a trivial patch. Designing + testing v0.2.x is a Stage 1+2 effort of roughly 2-3 weeks before any benchmark numbers exist.

## Performance side-observations

| Run | Wall time | Per-add | JSON errors | Records produced |
|---|---|---|---|---|
| 1 (v0.1.8, 10d) | 3731 s | 186.55 s | 3/20 | 78 |
| 2 (v0.1.8, 90d, 0.6) | 4267 s | 213.36 s | 4/20 | 56 |
| 3 (v0.1.2, 10d) | 5874 s | 293.69 s | (errors visible in log; count not extracted) | 58 |

phi3:mini's JSON-mode reliability is the bottleneck across all three. Graphiti's multi-call extraction pipeline (entity extraction + edge extraction + entity dedup + edge dedup) compounds the cost of each JSON failure because retries restart the chain. The fact that production deployments would use a stronger LLM (gpt-4o-mini, claude-3-haiku, llama3.1:70b) doesn't change the architectural finding above; it would just make these runs faster.

## What this changes operationally

1. **The Mem0 + v0.1.8 production recommendation stands** ([`docs/runbook-mem0-v0.1.8-deploy.md`](runbook-mem0-v0.1.8-deploy.md)). Customers running Mem0 will see the measured numbers.
2. **The Graphiti + Cognee adapters remain real code** that future v0.2.x variants will use. The integration work is preserved.
3. **The synthesis plan's "production-shape for any of three frameworks" framing needs a footnote** ([`docs/synthesis-memory-lifecycle-management.md`](synthesis-memory-lifecycle-management.md)). Production-shape for Mem0, awaiting v0.2.x for the others.
4. **The Cognee F1 benchmark is now lower-priority.** Strong prior that it would show the same 0% reduction pattern. Better to design v0.2.x before running it.

## What this changes about the framework's credibility

This is the kind of finding the framework was built to surface. Pre-framework, the flow would have been: "shipped three adapters, they all pass tests, declare victory." Post-framework: "shipped three adapters, ran end-to-end benchmarks, three runs caught an architectural assumption that was baked in unknowingly, the finding doc is now part of the public record."

The credibility-bearing artifact is not "the framework produces high numbers." It's "the framework surfaces real limitations and documents them in the open." Two examples now: the entity-norm Stage 3→4 ranking flip and this one.

## Decisions

1. Update [`docs/synthesis-memory-lifecycle-management.md`](synthesis-memory-lifecycle-management.md) with the v0.2.x design implication
2. Update [`README.md`](../README.md) to caveat the "three adapters" framing
3. Defer Cognee F1 benchmark until v0.2.x exists OR until someone needs the negative-result confirmation explicitly
4. Add v0.2.x design to the framework backlog as Opportunity 2 Phase 5

## Pointers

- Benchmark script: `experiments/graphiti_retrieval_f1_benchmark.py`
- Artifacts: `runs/graphiti_retrieval_f1/202606{08,09}T*.json`
- Adapter: `runner/dimensions/memory/lifecycle/integrations/graphiti_adapter.py`
- Variants: `runner/dimensions/memory/lifecycle/{ref_count,comprehensive_tuned}.py` (where the in_degree==0 check lives)
- Variant lineage rationale: `docs/finding-gc-tombstone-api-and-v017.md`
- Companion Mem0 result: `docs/finding-mem0-f1-stage5.md`
- Companion Mem0 reduction smoke: `docs/finding-mem0-adapter-real-llm-stage5.md`
- Synthesis plan (needs v0.2.x footnote): `docs/synthesis-memory-lifecycle-management.md`
