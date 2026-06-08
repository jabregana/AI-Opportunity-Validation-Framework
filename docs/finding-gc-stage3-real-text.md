---
type: finding
opportunity: real-time graph GC for agent memory
stage: 3
status: PASS
date: 2026-06-07
artifact: runs/gc_stage3_real_text/20260607T211236.json
---

# Stage 3 finding: v0.1.2 fact-only GC holds up on real Twitter text

The Stage 2 revision finding ([`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md)) showed v0.1.2 passes all four UC gates on the synthetic graph-churn workload. Stage 3's job is to show whether that result survives real-text-input with real entity distribution. It does.

**Headline**: on 627 real Twitter Financial News tweets with 111 real entities, **v0.1.2 reduces store size by 84.96% while preserving 100% of entities and collecting zero expected survivors falsely. All four UC gates pass.**

This is the second case study to complete a Stage 3 within the framework (the first being the schema-alignment proxy).

## What "Stage 3" means here

The framework's discipline ([`../FRAMEWORK.md`](../FRAMEWORK.md)) defines Stage 3 as "real data, small N." Concretely for this opportunity:

- **Real text input**: Twitter Financial News validation split (the same data the proxy used at its Stage 3 / 4).
- **Real entity distribution**: 111 entities from the 125-entity / 416-alias curated map (`CURATED_ENTITIES` in `experiments/case_study_expanded.py`), filtered to those that actually appear in tweets.
- **Real surface-form diversity**: each tweet may mention 1-3 entities via any of the 416 aliases.
- **Real entity-frequency Zipfian**: top-10 entities range from 31 (Tesla) to 23 (Goldman Sachs) mentions; long tail of entities with single-digit mentions.

What is still simplified (and therefore reserved for Stage 4 or full Stage 3 with downstream integration):

- **Temporal model is synthetic.** Tweets are assigned timestamps `i * tick_seconds` rather than real publication times. Edge-removal events fire deterministically at `t + fact_lifetime`. Real ingestion has more irregular timing.
- **Extraction is deterministic-regex, not LLM.** The proxy at full Stage 3 used 14 LLMs to extract canonicals; this GC run uses the alias-map regex match. That choice is correct for GC evaluation (known-good entity boundaries are needed so correctness can be scored against ground truth), but it does mean the workload has more uniform extraction noise than a real LLM ingestion would.
- **No Mem0 / Graphiti / Cognee runtime in the loop.** The benchmark runs the variant against an in-memory graph state, not behind a real memory framework's write path. That blocks measuring the integrated latency / API overhead.

These are honest limitations. The framework's discipline says they belong in a Stage 3.5 / Stage 4 follow-up rather than blocking the Stage 3 verdict.

## Setup

- **Data**: `zeroshot/twitter-financial-news-topic` validation split (loaded via `datasets`)
- **Alias map**: imported from `experiments/case_study_expanded.py` (125 canonicals, 416 aliases)
- **Per-entity cap**: 20 tweets per primary canonical
- **Workload params**: `tick_seconds=600` (10 min between tweets), `fact_lifetime_days=7`, `pin_top_k=5`
- **Variants**: `b-raw-no-gc` (baseline) + `gc-v0.1.2-fact-only`. v0.1.0 / v0.1.1 omitted because their Stage 2 revision verdict already established they fail under conservative-survival semantics.
- **Runner**: `runner/gc_runner.py` with default sweep cadence

## Results

| Metric | b-raw-no-gc | **gc-v0.1.2-fact-only** |
|---|---|---|
| Tweets loaded | 627 | 627 |
| Entities discovered | 111 | 111 |
| Events generated | 2347 | 2347 |
| Pinned (top-5 by frequency) | 5 | 5 |
| Expected survivors | 111 | 111 |
| Nodes added | 738 | 738 |
| Nodes collected | 0 | **627** |
| Nodes at end | 738 | **111** |
| Store reduction % | 0.00 | **84.96** |
| Surviving entities | 111 | 111 |
| False collections | 0 | **0** |
| Write p50 (ms) | 0.0002 | 0.0002 |
| Write p99 (ms) | 0.0009 | 0.0005 |
| Sweep total (s) | 0.0000 | 0.0020 |

### UC gates

| Gate | gc-v0.1.2-fact-only |
|---|---|
| UC-GC-1 (store reduction >= 0%) | **PASS (84.96%)** |
| UC-GC-2 (entity recall vs baseline >= 95%) | **PASS (100%)** |
| UC-GC-3 (false-collection rate <= 1%) | **PASS (0%)** |
| UC-GC-4 (write p99 <= 10 ms) | **PASS (0.001ms)** |

All four pass.

## Why the store reduction dropped from 97.56% (Stage 2) to 84.96% (Stage 3)

The synthetic workload had a deliberately skewed ratio: 2000 facts to 50 entities (40:1). Real text is much less skewed: 627 facts to 111 entities (5.6:1). When entities are a larger share of the store, the ceiling on "fact-only collection" reduction is naturally lower.

This is not a regression. It is the framework's discipline doing exactly what Stage 3 is supposed to do: surface the real-shape numbers so the headline reflects production-shape reality rather than synthetic-bias overclaims.

## Top entities by mention frequency (for context)

```
Tesla Inc                      31
Federal Reserve                29
Netflix Inc                    28
Apple Inc                      27
Amazon Inc                     27
Bitcoin                        27
S&P 500                        27
Dow Jones                      26
Bank of America                24
Goldman Sachs                  23
```

The top-5 are pinned (Tesla, Fed, Netflix, Apple, Amazon). All 5 pinned entities survive. All 111 entities discovered in the tweet stream survive (the surviving-entity count exactly matches `n_entities`).

## Honest read

### What this finding earns

- **A second case study at Stage 3.** The framework now has two completed Stage 3 results (proxy and GC). That is two opportunities, not one, that survived the framework's full discipline.
- **The framework's pattern transfers.** Stage 3 for the GC opportunity used the same `experiments/` script shape, the same `runs/<benchmark>/<timestamp>.json` artifact pattern, the same UC-gate table as the proxy's Stage 3. No framework-level changes were needed.
- **The conservative-survival philosophy holds up on real text.** No entities were collected incorrectly under the v0.1.2 rule, even though real-text entity arrival is Zipfian (long-tail entities appear in just one or two tweets each).

### What this finding does NOT earn

- **Full Stage 3 with downstream integration.** This run did not put the variant behind a Mem0 / Graphiti / Cognee write path. That would test integrated latency and any API overhead. The deferred work is documented as a Stage 3.5 / 4 task.
- **A claim about adversarial workloads.** Burst patterns (1000 facts in a second targeting one entity), pathological queries (queries against just-collected facts), concurrent reads during sweep, partial-overlap edge supersession (one of a fact's edges removed while another stays): all untested.
- **A multi-tenant claim.** The workload has no tenant scoping. `pinned` is global. A real deployment with N tenants would need scoped pinning and scoped sweeps.
- **Latency at scale.** 2347 events with sub-microsecond per-event timing does not stress the write path. Stage 4 should run at 100k+ events.
- **A real-LLM extraction comparison.** The deterministic regex extraction is known-good (it cannot make extraction errors) so the GC variant has the easiest possible input. Real LLM extraction introduces canonical-ID noise that may interact with the fact-collection rule in ways this run does not exercise.

### Where the Stage 4 / production-readiness work should focus

In priority order:

1. **Integration shim for a real downstream system.** Build `runner/dimensions/memory/lifecycle/integrations/graphiti.py` or similar that hooks v0.1.2 into Graphiti's write path. Measure integrated latency.
2. **Multi-tenant pinning.** Add `pinned: dict[tenant_id, set[node_id]]` to `GraphState` and a sweep that respects tenant scope.
3. **Burst / adversarial workloads.** Add `fixtures/workloads/w_graph_churn_adversarial.py` with the patterns the honest-read identified.
4. **Real ingestion traces.** If the user has access to any production Mem0 / Graphiti ingestion traces, replay them through v0.1.2 and measure. (Not a substitute for the synthetic adversarial workloads, but complements them.)
5. **Scale.** Re-run with 100k+ events. Stage 2's per-event timing budget (10ms p99) may or may not survive that scale; need to know before any production claim.

## Decision

Promote v0.1.2 toward Stage 4. Stage 4 should be the integrated-runtime test (item 1 above) rather than just a scale-up of the in-memory benchmark, because the per-event latency at sub-microsecond is bottlenecked by Python dict mutation, not by any algorithmic concern.

## Pointers

- Code: `experiments/gc_stage3_real_text.py` (this benchmark)
- Variant: `runner/dimensions/memory/lifecycle/ref_count.py::FactOnlyGC` (after migration; backward-compat shim at `runner/gc_variants/ref_count.py`)
- Workload generator: `fixtures/workloads/w_graph_churn.py` (Stage 2 synthetic) + the in-script workload-from-tweets builder (Stage 3 real-text)
- Prior findings: [`finding-gc-stage2-baseline.md`](finding-gc-stage2-baseline.md), [`finding-gc-stage2-revision-v0.1.2.md`](finding-gc-stage2-revision-v0.1.2.md)
- Opportunity scan: [`opportunity-graph-gc.md`](opportunity-graph-gc.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/gc_stage3_real_text.py
# Defaults: per_entity_cap=20, tick_seconds=600, fact_lifetime_days=7,
#           pin_top_k=5. Loads Twitter Financial News validation
#           split via Hugging Face datasets (cached after first run).
```
