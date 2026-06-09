---
type: opportunity
stage: 1
date: 2026-06-09
status: WEDGE-CONFIRMED-CONFIGURABILITY-DESIGNED
opportunity_id: opp-002-phase-5
parent: opportunity 2 (Agent Memory Lifecycle Management), phase 5
supersedes: portion of finding-graphiti-f1-stage5.md ("the architectural limitation needs a new variant family")
---

# Opportunity 2 Phase 5: v0.2.x graph-topology GC variants for edge-rich frameworks (Graphiti, Cognee)

## Wedge summary

The v0.1.x variant family produces 0% reduction on Graphiti because its `in_degree == 0` orphan check rarely triggers in edge-rich graphs. The Mem0 path is unaffected (flat-memory framework; in_degree trivially 0). The wedge: build a v0.2.x variant family with graph-topology-aware collection rules + per-deployment configurability, so customers running Graphiti or Cognee get the same "deploy-then-measure" loop the Mem0 customers get.

Three industry signals converge on this being a real wedge:

1. **Graphiti ships the temporal infrastructure but not the GC.** `EntityEdge` has three temporal fields (`valid_at`, `invalid_at`, `expired_at`). Zero modules with `prune` / `gc` / `sweep` / `cleanup` / `expire` in the name. The `expired_at` field strongly suggests Graphiti's data model anticipated TTL semantics but never shipped the sweep.
2. **Adjacent work targets retrieval-time pruning, not write-path GC.** HippoRAG (PPR ranking), PathRAG (flow-based retrieval pruning), GraphRAG (community-detection retrieval) all live at query time. None of them collect (delete) anything. The agent-memory store still grows unboundedly on those systems.
3. **The Mem0 + v0.1.8 customer story is already in motion.** A v0.2.x family extends the same product (Agent Memory Lifecycle Management) to the graph-native side of the incumbent landscape without rebuilding the framework.

## Is this already shipped?

Verified what's available. Status as of 2026-06-09:

| Project | What they ship | GC for graph-native memory? |
|---|---|---|
| **Graphiti** (Zep) | Bi-temporal entity graphs, search, episode model | NO. Has `remove_episode` (delete a single named episode); no sweep, no TTL execution, no policy-driven collection. Temporal fields exist but unused for deletion. |
| **Cognee** | Module-level memory pipeline with cognify() | Unverified, low prior. The framework's design centers on building knowledge graphs from raw text; collection appears not to be in scope. Stage 1 scan task: confirm. |
| **HippoRAG** | Personalized PageRank for multi-hop QA retrieval | NO. Query-time ranking only; the knowledge graph grows monotonically. |
| **PathRAG** | Flow-based pruning of retrieval paths | NO. Query-time pruning of retrieved subgraphs, not write-path collection. |
| **GraphRAG** (Microsoft) | Community detection over entity graphs | NO. Query-time retrieval optimization. The underlying graph is never reduced. |
| **Memgraph MAGE** | Library of graph algorithms (PPR, community detection, etc.) | NO. Just algorithm primitives. Not a GC system; you would build one on top. |
| **Neo4j APOC** | Standard library extension | NO. Includes `apoc.periodic.iterate` for batch operations, but no GC-as-a-policy. |
| **Mem0 v2** | The framework v0.1.x targets | Has its own internal `update` (merging contradictions) but no GC. The Mem0+v0.1.8 work shipped earlier this week is the answer for Mem0. |

**Conclusion: the wedge is wide and open.** No incumbent ships write-path GC for graph-native memory frameworks. The closest competitors are retrieval-time pruners (HippoRAG, PathRAG, GraphRAG), which solve a different problem.

## The three verification questions (Stage 1 follow-ups)

These three need answering before committing to v0.2.x designs. Each is roughly half a day of work.

### Q1: Does Graphiti actually set `invalid_at` and `expired_at` reliably?

What is known: the fields exist on `EntityEdge`. What is not known: under what conditions Graphiti's extraction layer populates them. The benchmark workloads run this week (SQuAD, single-context-per-add) never trigger supersession because each SQuAD context is a standalone fact.

**Verification approach**: build a 2-step workload where the second add explicitly contradicts the first (e.g., "User likes coffee" then "User now drinks only tea"). Run through Mem0GCMiddleware-equivalent wrapper for Graphiti, query Neo4j directly, check whether the original "likes coffee" edge has `invalid_at` set. If yes, v0.2.1-temporal-validity is cheap. If no, the variant has to instrument supersession detection itself.

### Q2: What's the per-node traversal-tracking overhead in Graphiti?

The activation-decay rule (v0.2.2) requires hooking into Graphiti's search path to update `last_traversed` on every returned node. Need to measure: how invasive is the hook, what's the latency cost per search.

**Verification approach**: patch the GraphitiGCMiddleware's `search()` method to bump a counter on every returned node. Re-run the Graphiti F1 benchmark with the hook enabled. Compare wall time vs without hook. If sub-1% overhead, ship the rule. If 5%+, redesign to amortize.

### Q3: Does Cognee expose temporal validity or only relationship strength?

If Cognee has equivalent temporal fields, v0.2.x designs work for both downstreams unmodified. If not, Cognee needs a different variant (probably activation-decay only, since temporal-validity wouldn't have data to read).

**Verification approach**: install Cognee, inspect its node/edge schema, document what's available. If temporal fields exist, plan v0.2.x for both. If not, plan Cognee-specific variant later.

## Configurability: the real design requirement

The framework's existing v0.1.x variants accept tunable knobs (`min_age_seconds`, `min_query_count`, `tombstone_ttl_seconds`). v0.2.x needs the same pattern PLUS explicit support for **per-deployment configuration profiles** so customers can pick a profile that fits their domain, model, and workload shape.

### What "configurable per domain / model / setup" actually means

Three orthogonal config axes that interact:

| Axis | Why it matters | Example values |
|---|---|---|
| **Domain** | Different knowledge domains have different fact-validity timescales | `financial-news` (hours), `clinical-records` (years), `general-knowledge` (months), `customer-conversations` (weeks) |
| **Model** | LLM extraction quality affects how cleanly facts can be classified | `qwen2.5:7b` (more noise, conservative collection), `claude-sonnet-4.6` (cleaner, more aggressive), `phi3:mini` (very noisy, very conservative) |
| **Setup** | Deployment shape changes the right cadence + thresholds | `single-tenant-low-volume`, `multi-tenant-saas`, `enterprise-batch-ingest`, `real-time-conversational` |

The product surface: a customer picks one profile from each axis. The framework loads the corresponding YAML config. Knobs that span all three axes (like the temporal-validity TTL) get composed via priority order: setup > domain > model > defaults.

### Concrete config shape

```yaml
# config/v0.2.x/profile.yaml
name: profile-finance-claude-sonnet-saas
domain: financial-news
model: claude-sonnet-4.6
setup: multi-tenant-saas

temporal_validity:
  enabled: true
  ttl_days: 7              # financial facts go stale fast
  use_field: invalid_at    # vs expired_at; framework-specific

activation_decay:
  enabled: true
  window_days: 30          # shorter than general-knowledge default of 60
  min_query_count: 2       # cleaner model -> can be more aggressive

component_isolation:
  enabled: true
  reachable_from_top_n_queried_nodes: 50
  min_subgraph_age_days: 30

rule_composition:
  collect_if: any          # OR across rules (vs all = AND)

tenant_pin:
  enabled: true            # SaaS deployment requires per-tenant respect
```

The framework loads this YAML, instantiates a `ComprehensiveGraphTopologyGC` variant configured from it, registers it under a deterministic name like `gc-v0.2.x-finance-claude-sonnet-saas`. Customer code becomes:

```python
variant = build("gc-v0.2.x-from-profile", profile="config/profiles/finance-claude-sonnet-saas.yaml")
mw = GraphitiGCMiddleware(graphiti)
mw.sweep(variant, current_time=time.time())
```

### Default profiles to ship with v0.2.0

A starter profile set so customers don't have to start from scratch:

| Profile | Domain | Model assumption | Setup | Use when |
|---|---|---|---|---|
| `general-default` | mixed | frontier (gpt-4o-class) | single-tenant | Out-of-the-box choice; conservative |
| `finance-aggressive` | financial | frontier | multi-tenant | Trading/news; facts go stale fast |
| `clinical-conservative` | healthcare | frontier | enterprise | Multi-year fact retention; over-collection is dangerous |
| `customer-conversations` | conversational | any | SaaS | Mem0-shape conversations |
| `local-model-conservative` | mixed | local 7B-class | any | Conservative because extraction is noisier |

Each profile lives at `runner/dimensions/memory/lifecycle/profiles/<name>.yaml` and is loaded by a new helper `runner/dimensions/memory/lifecycle/profile_loader.py`. This is a small addition (~150 lines) and follows the framework's existing pattern of factory-registered variants.

## The seven-layer candidate design for v0.2.x

Subsequent design discussion expanded the initial four-variant sketch into a seven-layer design space. Five layers are in scope for v0.2.x (cheap-to-moderate cost, clear signal); two are deferred to v0.3.x (more expensive, more research-shaped).

Each layer exists as its own variant class so it can be enabled / disabled / composed independently via the deployment profile. Same compositional pattern as v0.1.x but with graph-topology-aware rules.

### v0.2.x: five production-shape layers

| Layer | Variant | Rule | Equivalent of / source |
|---|---|---|---|
| 1. Subgraph inactivity | `gc-v0.2.0-component-isolation` | Detect connected components not reachable from top-N most-recently-queried nodes; collect the whole component | New pattern; subgraph-orphan rule for graph-native |
| 2. Validity-window | `gc-v0.2.1-temporal-validity` | Collect facts where `now - invalid_at > config.ttl_days` (or `expired_at` if Graphiti uses that field) | v0.1.2 fact-only adapted; uses Graphiti's native temporal fields |
| 3. Edge-decay / activation | `gc-v0.2.2-activation-decay` | Collect nodes where `now - last_traversed > window_days AND query_count < min_query_count AND invalid_at is null` | v0.1.7 tuned-entity adapted; covers edge-weight decay as a special case |
| 4. Evidence-count | `gc-v0.2.3-evidence-count` | Keep entities always; collect "evidence" nodes (episodes, mentions, source documents) that have been superseded by newer evidence supporting the same entity | New pattern; preserves the entity layer while pruning the source-document churn |
| 5. Supersession with explicit tombstone | `gc-v0.2.4-supersession-tombstone` | When a fact is replaced by a newer fact (LLM extracts a contradiction), tombstone the old fact instead of immediately deleting. Tombstone retains the fact's id + summary for over-collection recovery (analog of v0.1.3 for graph-native) | v0.1.3 tombstone log adapted; pairs with Layer 2 |
| Bundle | `gc-v0.2.5-comprehensive-tuned` | Composes all five layers above + v0.1.5 tenant pinning, configurable per profile | v0.1.8 comprehensive-tuned analog |

### v0.3.x: deferred research layers

| Layer | Variant | Rule | Why deferred |
|---|---|---|---|
| 6. Retrieval-impact guardrail | `gc-v0.3.0-retrieval-impact-guardrail` | Meta-rule: before any layer fires, simulate the F1 impact of the proposed collection on a held-out query workload. Abort the collection if F1 drop exceeds threshold | Requires a "shadow" F1 measurement at sweep time, which means running real queries on the proposed-deleted set. Adds non-trivial wall time per sweep. Genuine value when collection is risky. |
| 7. Compression / summarization | `gc-v0.3.1-cluster-summarization` | Instead of binary keep/delete, summarize large clusters of stale facts into a single derived "summary node" that preserves the gist. Original facts collected, summary retained | Different data-model abstraction (introduces derived nodes). Requires LLM in the GC loop (cost change). Different evaluation harness (need to measure "summary fidelity" not just F1). |

The v0.3.x layers are documented here so the design space is clear, but engineering them is reserved for after v0.2.x has measured numbers. Personalized PageRank (mentioned earlier as one option) folds into Layer 1 (component isolation) as a more principled scoring approach; it remains a research-tier alternative within Layer 1's design space.

The seven-layer framing comes from a separate design discussion that synthesized incumbent patterns (Anki/SuperMemo forgetting curves, HippoRAG-style PPR, Graphiti's bi-temporal model) into a single ladder ordered by implementation cost. The layers above are roughly cost-ordered: Layer 1 is the cheapest, Layer 7 is the most expensive.

## What the workload needs to look like to actually exercise v0.2.x

Critical realization from the Graphiti F1 benchmark experience: **SQuAD is the wrong workload for this variant family.** Every SQuAD context is a standalone fact with no supersession, no domain-specific staleness, and no natural graph clustering. v0.2.1 (temporal validity) literally cannot fire because nothing ever gets superseded.

The right workload shape for v0.2.x stage 2 testing:

```
fixtures/workloads/w_graph_lifecycle.py
  Generates synthetic episodes with:
    - 40% standalone facts (no supersession; never trigger v0.2.1)
    - 30% supersession sequences (A states X, B states "not X anymore")
    - 20% multi-fact episodes that form natural subgraph clusters
    - 10% queries against subsets to exercise activation patterns
  Configurable parameters:
    - total_period_days (sets the wall-clock for validity expiration)
    - n_topics (controls subgraph cluster count)
    - query_distribution (uniform, zipfian, recency-biased)
    - supersession_rate (fraction of facts that get invalidated)
```

This is roughly 1 day to build. Existing `w_graph_churn.py` is the wrong shape (it includes edge-removal events that don't happen in real Graphiti).

### Synthetic data generation: the five-step approach

Building `w_graph_lifecycle.py` follows the standard synthetic-data generation discipline from [`docs/benchmark-methodology.md`](benchmark-methodology.md). Concrete steps for this opportunity:

1. **Domain analysis**: Study real-world memory graphs in the target deployment domain. For initial Stage 2 testing without customer data, study published agent-memory traces (e.g., LongMemEval, MemGPT-bench) and the schemas exposed by Graphiti and Cognee (their data-model docs describe expected node/edge cardinalities).
2. **Realistic patterns**: Use parametric generators that mirror real distributions. For graph-native memory the relevant distributions are: scale-free node degree (Barabasi-Albert), heavy-tail fact-lifetime (Weibull with shape < 1), Zipfian query frequency over entities, log-normal entity-evidence count. Implement via `networkx` for graph generation + `numpy` for the per-axis distributions.
3. **Scaling**: Parameterize the generator so the same call produces 100 facts or 100,000 facts with the same shape. Workload tests run at multiple scales per the volume-sufficiency requirement (1x, 4x, 10x converged-live-set).
4. **Sanity checks**: After generation, validate aggregate statistics match expected shapes: node-degree histogram (should be heavy-tailed), supersession-rate (should match the requested fraction), subgraph-component count (should match `n_topics` parameter). The methodology standard requires a validation block in the finding doc.
5. **Iterate**: Start at n=100 (smoke test), validate the variant's behavior is sensible, then scale to n=1000 and n=10000. Per the methodology, don't ship a Stage 3 finding from an unvalidated workload.

This approach gives the framework a defensible answer to "did you tune the workload to flatter your variant?" because each generation parameter is sourced from a documented distribution rather than picked to produce a desired result.

## Benchmark methodology (compliance with the framework standard)

v0.2.x is a Stage 3+ opportunity, so it must comply with [`docs/benchmark-methodology.md`](benchmark-methodology.md). The key methodology requirements applied to this opportunity:

### Workload archetypes (must run AT LEAST 3 of the 5 standard archetypes plus the adversarial one)

| Archetype | Fixture | v0.2.x specifics |
|---|---|---|
| **Steady-state** | `w_graph_lifecycle.py` with `supersession_rate=0.0, n_topics=1` | Baseline behavior; should match Mem0+v0.1.x reduction shape |
| **High-mutation / supersession-heavy** | `w_graph_lifecycle.py` with `supersession_rate=0.5` | Required to exercise v0.2.1-temporal-validity AND v0.2.4-supersession-tombstone; the rules cannot fire without supersession events |
| **Cluster-rich** | `w_graph_lifecycle.py` with `n_topics=10, query_distribution=zipfian` | Exercises v0.2.0-component-isolation; without distinct subgraphs the rule has nothing to isolate |
| **Adversarial (variant-specific)** | NEW: `w_graph_no_supersession_no_isolation.py` | Designed to defeat v0.2.x: rich connectivity, no supersession events, no isolated subgraphs. If v0.2.x cannot handle this case, the finding doc documents it as out-of-scope rather than hiding it. |
| Real-data sanity | Graphiti + SQuAD subset (existing benchmark) | Confirms the variant does NOT regress on the workload that the Mem0 path already runs |

### Volume protocol (5-cell matrix per variant)

Each variant gets benchmarked across this grid:

| n_pairs | Seeds | Store-size multipliers |
|---|---|---|
| 50, 200, 1000 | {42, 123, 456} | 1x, 4x, 10x converged-live-set |

Total: 3 N values × 3 seeds × 3 store sizes × 4 archetypes = **108 runs per variant**. At ~5 min average per run that is roughly 9 hours of Ollama time per variant. Acceptable.

For the comprehensive bundle (v0.2.5) and the headline cross-framework comparison, the full matrix runs. For exploratory v0.2.0 / v0.2.1 / v0.2.2 / v0.2.3 / v0.2.4 individual-rule iterations, a reduced grid (1 N × 3 seeds × 1 store size × 2 archetypes) is acceptable during dev, with the full matrix run before any finding doc ships.

### Variance + significance reporting

Every headline metric reported as `<mean> [<ci_low>, <ci_high>] (n_seeds=3)` using `runner/metrics/stats.py::paired_bootstrap`. The Graphiti F1 numbers landed this week as point estimates; v0.2.x numbers ship from day one with bootstrap CIs.

### Pre-registration ritual

Before each variant's Stage 3 run, the corresponding finding doc gets a pre-registration block (per the template in [`docs/benchmark-methodology.md`](benchmark-methodology.md)) stating the metrics, thresholds, and decision rules. After the run, the post-run block reports observed values against those exact thresholds. Gates are not moved post hoc.

For v0.2.x specifically, the pre-registered UC gates are:

```yaml
pre_registered_gates:
  uc_gc_retrieval_min_f1_preservation: 80.0   # same as Mem0 v0.1.8
  uc_gc_min_reduction_when_workload_aged: 30.0  # at least 30% reduction on supersession-heavy archetype
  uc_gc_max_false_collection_pct: 1.0         # same as Mem0 v0.1.8
  uc_gc_max_sweep_p99_seconds: 5.0            # 10x the Mem0 v0.1.8 limit (graph algorithms are more expensive)
  uc_gc_max_search_overhead_pct: 5.0          # v0.2.2 traversal-tracking hook overhead ceiling
```

If v0.2.x fails any pre-registered gate on the adversarial archetype, the variant ships as DEFER or DO-NOT-BUILD rather than rebuilding the gate.

### Sourcing strategy (tiered)

| Tier | Source | Status for v0.2.x |
|---|---|---|
| 1 | Production telemetry from customer pilot | UNAVAILABLE until customer pilot exists |
| 2 | Parametric fits to Mem0 2000-input smoke (1.68x amplification, sweep oscillation pattern) | Available now; will be used to calibrate steady-state archetype |
| 3 | Public corpora as sanity floor: SQuAD (existing), LongMemEval, MemGPT-bench | LongMemEval + MemGPT-bench should be added; treat as Stage 1 task |
| 4 | Synthetic with documented parametric model | Default for archetypes that have no real-data analog |

### Updated cost estimate

The benchmark-methodology compliance plus the expansion from four variants to five layers (plus the v0.3.x research layers documented above) updates the original scope:

| Phase (updated 2026-06-09) | Effort |
|---|---|
| Stage 1 verification (Q1, Q2, Q3) + landscape deeper scan | 2-3 eng-days |
| Workload archetype library: lifecycle + adversarial + supersession-validation | 2 eng-days |
| v0.2.0-component-isolation variant + tests | 3 eng-days |
| v0.2.1-temporal-validity variant + tests | 2 eng-days |
| v0.2.2-activation-decay variant + tests | 2 eng-days |
| v0.2.3-evidence-count variant + tests (new layer) | 2 eng-days |
| v0.2.4-supersession-tombstone variant + tests (new layer) | 2 eng-days |
| v0.2.5-comprehensive-tuned bundle + profile loader (5 starter profiles) | 3 eng-days |
| Stage 2 benchmark with multi-seed + multi-archetype matrix (all 5 variants) | 3 eng-days |
| Stage 3 real-Graphiti F1 with full compliance matrix | 2 eng-days |
| Stage 4 multi-vertical scale-up | 2-3 eng-days |
| Retroactive: add CIs to existing Mem0 + Graphiti finding docs | 1 eng-day |

**Updated total: 26-29 engineer-days (was 22-23), roughly 5-6 calendar weeks of focused work.**

The bump from 22-23 to 26-29 reflects the two added layers (evidence-count + supersession-tombstone). Layer 4 + Layer 5 are the most analogous to Mem0+v0.1.x's tombstone-and-tenant features, which means the v0.2.5 bundle would be a closer apples-to-apples comparison with the Mem0 + v0.1.8 deployment recipe.

v0.3.x layers (retrieval-impact-guardrail + cluster-summarization) are explicitly out of this scope. Engineering them is a separate ~3-4 week effort that would happen after v0.2.x has measured numbers.

Half the value of v0.2.x is that the numbers survive hostile review. The retroactive Mem0 CI addition (1 day) is mandatory regardless of v0.2.x funding because the existing 81.6% headline is currently a single-seed point estimate.

## Why this could fail (risk register)

Honest list of ways v0.2.x might not produce defensible numbers:

1. **Graphiti's `invalid_at` is never set in practice.** If the extraction layer doesn't reliably detect supersession, v0.2.1 and v0.2.4 have no signal to act on. Verification Q1 answers this. If the answer is "no," the variants have to do their own supersession detection, which is a research project.
2. **Activation tracking adds significant search overhead.** Hooking into every search to update `last_traversed` may be too invasive on hot paths. Verification Q2 answers this. Mitigation: amortize by sampling (only update on 1 in K searches).
3. **Component-isolation cost scales poorly.** Detecting connected components on a million-node graph requires either incremental algorithms (Tarjan's SCC adapted for streaming) or expensive periodic recomputation. Performance budget needs careful design.
4. **PPR temptation creeps in.** If v0.2.x's simple rules underperform, the obvious "fix" is to add PPR. PPR over a real graph is expensive and the right Stage 3 question is "is PPR worth its compute cost vs cheaper rules?" Discipline: do NOT add PPR until v0.2.x has measured numbers without it.
5. **Profile complexity explodes.** If every domain/model/setup combination needs a hand-tuned profile, the framework becomes a hairball. Mitigation: ship 5 starter profiles; document the knob ranges; refuse to write per-customer profiles before there is a customer.
6. **Cognee turns out to be too different.** If Cognee doesn't expose temporal validity in any usable form, v0.2.x splits into "graphiti family" and "cognee family" with shared base. Bigger surface; still defensible but more work.

## Decision criteria: when to fund vs kill

Fund v0.2.x when:
- Q1 confirms Graphiti sets `invalid_at` for at least 60% of contradicted facts in a controlled supersession workload
- Q2 confirms activation-tracking overhead is below 5% on typical search workloads
- Mem0 + v0.1.8 has either a customer pilot in progress OR a credible 4-week timeline to one
- No incumbent has shipped graph-native GC in the meantime (recheck before kicking off Stage 2)

Kill v0.2.x when:
- Q1 returns "no" AND building supersession detection is more work than building a vector-based "fact freshness" classifier (which would be its own opportunity)
- An incumbent ships graph-native GC during Q1/Q2 verification (the wedge closes)
- Mem0 customer pilot fails (signal that the framework's positioning is wrong; v0.2.x doesn't fix that)

## What this changes operationally

If funded:

- The synthesis plan's Phase 5 row gets a concrete delivery target
- The README's "Graphiti / Cognee path" commercialization row gets a fix-it timeline
- The customer pilot conversations gain a second card to play (the Mem0 bundle today, the Graphiti bundle in ~4 weeks)
- The framework's per-domain configurability becomes a first-class product surface, not just a knob list
- The finding-doc record gains a third "framework caught itself" entry once Stage 2 shows v0.2.x actually works on the new workload

If killed (e.g., because Q1 returns "no"):

- The Mem0 path becomes the only commercializable bundle
- The synthesis plan's footnote becomes permanent rather than "pending v0.2.x"
- The graph-native frameworks (Graphiti, Cognee) get categorized as out-of-scope for the AML product
- That's still a valid outcome; some opportunities should die

## Pointers

- Parent finding (the architectural surface that produced this opportunity): [`finding-graphiti-f1-stage5.md`](finding-graphiti-f1-stage5.md)
- Sibling Mem0 numbers: [`finding-mem0-adapter-real-llm-stage5.md`](finding-mem0-adapter-real-llm-stage5.md), [`finding-mem0-f1-stage5.md`](finding-mem0-f1-stage5.md)
- v0.1.x variant lineage: [`finding-gc-tombstone-api-and-v017.md`](finding-gc-tombstone-api-and-v017.md)
- Original opportunity landscape scan: [`opportunity.md`](opportunity.md)
- Synthesis plan: [`synthesis-memory-lifecycle-management.md`](synthesis-memory-lifecycle-management.md)
