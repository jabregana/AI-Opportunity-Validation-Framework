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

What we know: the fields exist on `EntityEdge`. What we don't know: under what conditions Graphiti's extraction layer populates them. The benchmark workloads run this week (SQuAD, single-context-per-add) never trigger supersession because each SQuAD context is a standalone fact.

**Verification approach**: build a 2-step workload where the second add explicitly contradicts the first (e.g., "User likes coffee" then "User now drinks only tea"). Run through Mem0GCMiddleware-equivalent wrapper for Graphiti, query Neo4j directly, check whether the original "likes coffee" edge has `invalid_at` set. If yes, v0.2.0-temporal-validity is cheap. If no, the variant has to instrument supersession detection itself.

### Q2: What's the per-node traversal-tracking overhead in Graphiti?

The activation-decay rule (v0.2.1) requires hooking into Graphiti's search path to update `last_traversed` on every returned node. Need to measure: how invasive is the hook, what's the latency cost per search.

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

## The four candidate variants in v0.2.x

Each variant exists as its own class so they can be combined or composed via the profile. Same shape as v0.1.x but with graph-topology-aware rules instead of orphan-detection rules.

| Variant | Rule | Equivalent of |
|---|---|---|
| `gc-v0.2.0-temporal-validity` | Collect facts where `now - invalid_at > config.ttl_days` (or `expired_at` if Graphiti uses that field) | v0.1.2 fact-only (single-axis sweep) |
| `gc-v0.2.1-activation-decay` | Collect nodes where `now - last_traversed > window_days AND query_count < min_query_count AND invalid_at is null` | v0.1.7 tuned-entity (multi-condition collection) |
| `gc-v0.2.2-component-isolation` | Detect connected components not reachable from top-N most-recently-queried nodes; collect the whole component | New pattern (no v0.1.x equivalent) |
| `gc-v0.2.3-comprehensive-tuned` | Composes v0.2.0 + v0.2.1 + v0.2.2 + v0.1.5 tenant pinning + v0.1.3 tombstone log, configurable per profile | v0.1.8 comprehensive-tuned |

`v0.3.x-personalized-pagerank` is reserved as a research variant for after v0.2.x has measured numbers. PPR is too expensive to ship as the first cut.

## What the workload needs to look like to actually exercise v0.2.x

Critical realization from the Graphiti F1 benchmark experience: **SQuAD is the wrong workload for this variant family.** Every SQuAD context is a standalone fact with no supersession, no domain-specific staleness, and no natural graph clustering. v0.2.0 (temporal validity) literally cannot fire because nothing ever gets superseded.

The right workload shape for v0.2.x stage 2 testing:

```
fixtures/workloads/w_graph_lifecycle.py
  Generates synthetic episodes with:
    - 40% standalone facts (no supersession; never trigger v0.2.0)
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

## Why this could fail (risk register)

Honest list of ways v0.2.x might not produce defensible numbers:

1. **Graphiti's `invalid_at` is never set in practice.** If the extraction layer doesn't reliably detect supersession, v0.2.0 has no signal to act on. Verification Q1 answers this. If the answer is "no," the variant has to do its own supersession detection, which is a research project.
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

## Cost estimate

| Phase | Effort | Output |
|---|---|---|
| Stage 1 verification (Q1, Q2, Q3) | 2 engineer-days | `docs/opportunity-v0.2.x-stage1-verification.md` with go/no-go on each question |
| Stage 1 deeper landscape (verify Cognee, recheck HippoRAG releases) | 1 engineer-day | Updates to this doc |
| v0.2.0-temporal-validity (variant + tests) | 2 engineer-days | First variant + unit tests |
| `w_graph_lifecycle` synthetic workload | 1 engineer-day | Workload generator + UC gates |
| v0.2.0 Stage 2 benchmark on synthetic workload | 1 engineer-day | `docs/finding-gc-v020-stage2.md` |
| v0.2.1-activation-decay variant | 2 engineer-days | Variant + traversal-tracking hook |
| v0.2.2-component-isolation variant | 3 engineer-days | Variant + incremental component detection |
| v0.2.3-comprehensive-tuned bundle + profile loader | 3 engineer-days | Bundle + 5 default profiles + YAML loader |
| Stage 3 real-Graphiti F1 benchmark (the headline number) | 1 engineer-day | `docs/finding-gc-v020-stage3-real-graphiti.md` |
| Stage 4 multi-vertical scale-up | 2-3 engineer-days | Confirms or corrects Stage 3 |

**Total: 18-19 engineer-days, roughly 3-4 calendar weeks for focused work.**

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
