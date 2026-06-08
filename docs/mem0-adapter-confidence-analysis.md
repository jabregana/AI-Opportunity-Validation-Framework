---
type: pre-work-analysis
date: 2026-06-08
status: PROPOSAL-FOR-PHASE-1
---

# Why the framework has enough confidence to build the Mem0 adapter (and what the framework still do not)

This doc addresses the prerequisite question before starting Phase 1: **is the latest variant lineup (especially `gc-v0.1.8-comprehensive-tuned`) good enough to invest engineering effort in real Mem0 integration?**

The honest answer: the framework has STRUCTURAL confidence but lack EMPIRICAL confidence. The Mem0 adapter is itself the next-best validation step. Building it surfaces what the framework cannot yet know.

## What the framework has strong confidence in

### Mechanism correctness (high)

8 GC variants in the factory. Each has:

- A specific, narrow rule expressed as `should_collect(node_id, state, current_time)`
- Unit tests covering the rule's positive and negative cases (19 tests for v0.1.3-v0.1.5, 11 for v0.1.6, 11 for v0.1.8, plus the 26 inherited from v0.1.0-v0.1.2)
- Composition tested when variants inherit from one another (v0.1.8 = v0.1.7 + tombstones + tenant pinning; all combination tests pass)

**Evidence**: 418 total tests passing; 0 known correctness bugs in the variant lineup.

**What this earns**: confidence that when v0.1.8 says "collect this fact," it is applying the documented rule correctly. The adapter does not need to second-guess the variant's decisions.

### UC gate coverage (medium-high)

Five UC-GC gates (UC-GC-1 store reduction, UC-GC-2 entity recall vs baseline, UC-GC-3 false-collection rate, UC-GC-4 write-path latency, UC-GC-5 tombstone recovery) computed by `runner/gc_runner.py::compute_uc_gates`. The differentiated benchmark (`finding-gc-differentiated-stage2.md`) and cadence matrix (`finding-gc-cadence-matrix.md`) showed:

- v0.1.2 passes 4/5 gates (no tombstone capability; UC-GC-5 NA)
- v0.1.3 passes 5/5 at sweep cadence <= 100 (95.5% tombstone recovery)
- v0.1.8 passes 4/5 at sweep cadence <= 100 (UC-GC-2 entity recall is workload-sensitive at 76%, just below the 95% threshold)

**Evidence**: the gates are well-defined; the framework can score any variant on any workload deterministically.

**What this earns**: when the Mem0 adapter runs, the framework will get the same per-gate verdicts on real Mem0 traffic that the framework gets on the simulator. If the gates fail on real data, the failure has a known shape (which gate, by how much).

### Integration contract correctness (high)

`runner/dimensions/memory/lifecycle/integrations/base.py` ships the `GCIntegrationShim` ABC with 7 required methods. `mock.py` implements it. The Stage 4 finding (`finding-gc-stage4-shim.md`) showed:

- A variant running through the shim produces identical results to the same variant running directly against an in-memory `GraphState`
- 18 contract tests pass (write recording, edge bookkeeping, query updates, pin protection, sweep idempotency, stats accounting)
- The contract is shape-correct: routing every workload event through the shim and letting v0.1.2 sweep gives EXACTLY the same Stage 3 numbers (84.96% reduction, 100% recall, 0 false collections) as the direct path

**Evidence**: 738 writes + 802 edges + 802 edge-removes routed correctly through the mock shim; final state matches direct-path state to four decimal places.

**What this earns**: the contract is the right abstraction. A Mem0 adapter implementing the same 7 methods (translating to real Mem0 API calls) will work, modulo Mem0's specific data shape.

## What the framework still lack confidence in

### Mem0's actual data shape (low)

Mem0 (in v3+) maintains an internal graph plus a vector store. The framework does NOT have:

- Documented schemas for Mem0's node IDs and edge structures
- Documented behavior of Mem0's `add()` when it implicitly creates entities + facts from text
- Documented hooks for intercepting Mem0's internal sweep / consolidation logic
- Stability guarantees: Mem0's internal schema may change between versions

**What this means for the adapter**: the FIRST piece of integration work is reverse-engineering Mem0's data shape from its source code. The adapter writer must:

1. Read Mem0's `Memory()` class
2. Identify the graph-store layer (Neo4j? Qdrant? Internal SQLite?)
3. Map Mem0's add/update/delete onto the framework's record_write/record_edge/record_remove_edge calls
4. Find the sweep hook (a periodic task? A per-write check?)

The framework's confidence here is LOW. The adapter is a discovery exercise, not a translation exercise.

### Real LLM ingestion patterns (low)

The framework's Stage 3 used deterministic regex extraction against the Twitter alias map. Real Mem0 deployments use an LLM (Claude / GPT) to extract entities from natural text. The LLM may:

- Generate duplicate entities for the same concept (the proxy's exact problem)
- Create entities with low quality (single-word, ambiguous)
- Miss entities (incomplete extraction)
- Hallucinate entities (extraction errors)

**What this means for the GC variants**: real-LLM-ingested graphs may have very different topology than the synthetic ones. The fact-to-entity ratio (currently 5.6:1 on Twitter), the in-degree distribution, the query-access patterns, all unknown for real Mem0 deployments.

**Net**: v0.1.8's `min_unaccessed_seconds=60d` and `min_query_count=3` defaults are calibrated to a synthetic workload. They MAY work on real Mem0 data; they may need significant retuning.

### Retrieval-quality measurement (none)

The framework's UC-GC-2 uses entity-survival-vs-baseline as a PROXY for retrieval quality. The framework has no measurement of:

- Whether queries that previously succeeded still succeed after a GC sweep
- Whether the retrieval F1 changes (better, worse, or stable) when 80% of facts are collected
- Whether end-user-perceived answer quality changes

**What this means**: even if the adapter runs successfully and v0.1.8 reduces a real Mem0 deployment by 80%, the framework cannot yet say "and quality is preserved" with confidence. Phase 3 of the synthesis plan addresses this.

### Long-running behavior (none)

All benchmarks compress 30-120 days of activity into single runs. The framework does NOT know:

- Whether the fact-to-entity ratio stays at 5.6:1 in real deployments over 90 days
- Whether dormant-entity fraction grows over time (intuition: probably yes, old users churn, their entities go quiet)
- Whether tombstone-recovery rate degrades over time (intuition: probably yes, TTL expires faster than queries arrive)

## What the adapter will produce that the framework cannot get otherwise

Building the Mem0 adapter is **itself the next-best validation**. After Phase 1 ships, the framework will know:

| Question | How the adapter answers it |
|---|---|
| Does the shim contract translate to real Mem0? | Yes/no, with a list of contract methods that needed special handling |
| Does v0.1.8 reduce a real Mem0 graph by ~80%? | Measured number on a chosen test corpus |
| Does the default `sweep_every_n_events=100` work? | Measured tombstone recovery on real query traffic |
| Are the `min_query_count` / `min_unaccessed_seconds` defaults right? | Measured false-collection rate on real entities |
| What does the per-call latency look like in front of real Mem0? | Measured p99 latency for record_write / sweep |
| Does this slot into a customer's existing Mem0 deployment in <1 day? | Yes/no, with friction notes |

Each row is something the framework cannot answer with synthetic benchmarks alone. **Phase 1 is the cheapest way to surface them.**

## The honest framing

The framework has reached the saturation point for synthetic-data validation:

- Mechanism: tested
- Statistical harness: tested
- Integration contract: tested (against mock)
- Cross-dim composition: tested
- Cadence sensitivity: characterized
- All eight variants: documented with use cases

What synthetic-data validation cannot tell us:

- How real Mem0 internals behave
- How real LLM ingestion creates graphs
- How real users query memory over time
- Whether the engineering work needed to deploy this is 1 day or 1 month

The Mem0 adapter is the wedge for getting all four. **If the adapter takes 2 weeks and reveals that v0.1.8's defaults need recalibration, that is exactly the kind of Stage 3 finding the framework's discipline is built for.** A finding doc like `finding-gc-stage5-real-mem0-calibration.md` would be the next major artifact.

## Risk register for Phase 1

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Mem0's API changes mid-implementation | Medium | High (rework) | Pin to a specific Mem0 version |
| Adapter discovers Mem0 needs internal access the framework can't get | Low | High (block) | Use Mem0's public API only; document what's blocked |
| v0.1.8's defaults are wildly wrong on real Mem0 | Medium | Medium (recalibration) | This is the EXPECTED finding; document calibration plan |
| Real LLM extraction creates graphs the framework can't measure | Medium | Medium (instrumentation) | Build instrumentation alongside adapter |
| Mem0 ships its own GC and obsoletes the framework | Low | High (kill) | Monitor Mem0 changelog; current Mem0 has no GC |

The highest-risk-impact item is the last one. The framework's current advantage is that Mem0 / Graphiti / Cognee all leave memory growth to the user. If any of them ship native GC, the framework's market shrinks. Building the adapter NOW (vs in 6 months) is partly a race against that.

## Recommended path forward

1. **Build the adapter against Mem0's public API only** (no internal hooks; treat Mem0 as a black box plus a small instrumentation surface)
2. **Start with a stub that runs locally** (Mem0 supports a local Qdrant + in-memory backend; no Anthropic / OpenAI API key needed for the basic flow)
3. **First benchmark: 100 synthetic Mem0.add() calls** (verify the contract works end-to-end)
4. **Second benchmark: a real text corpus through Mem0's LLM extraction + adapter sweep** (the credibility-anchor result)
5. **Finding doc: `finding-mem0-adapter-stage5.md`** with measured numbers, friction notes, and the calibration questions surfaced

If steps 1-3 take more than 1 engineer-week, escalate: probably Mem0's API needs more reverse-engineering than expected, and the adapter scope should narrow.

## The bottom line for the user's question

Are the latest variants good enough to invest in adapter work?

**Yes, with two caveats.**

1. The variants are correct enough that the adapter can trust them: v0.1.8's `should_collect` decisions don't need second-guessing.
2. The variants' *defaults* (sweep cadence, age thresholds, query-count thresholds) are calibrated to a synthetic workload. The adapter run will tell  whether to keep them or retune.

The adapter is the right next bet because everything the framework don't know about the variants requires real downstream data to learn. The framework has done what synthetic benchmarks can do; the next 80% of value is in real-data deployment.
