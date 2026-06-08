---
type: business-kpi-mapping
opportunity: memory (lifecycle / graph GC)
date: 2026-06-08
confidence: low
---

# Business KPI mapping: memory lifecycle (graph GC)

Bridges the framework's technical lift on the graph-GC opportunity (84-97% store-size reduction with 100% entity recall) to candidate business KPIs. **Confidence: low.** Numbers below are illustrative.

## Technical metric

**Store-size reduction** of an agent memory graph using `gc-v0.1.2-fact-only` to collect facts whose outgoing edges have all been removed. Stage 3 finding: 85% reduction on real Twitter data, 0 false collections, 0 entities lost.

## Candidate business KPI bridges

### Bridge 1: infrastructure cost reduction

A graph 85% smaller costs ~85% less to store + ~85% faster to query (rough; index types vary).

- **Mechanism**: a 1M-fact agent memory deployment becomes a ~150K-fact deployment
- **Storage savings**: at Neo4j Aura ($0.10/GB/hour for the Pro tier, ~$72/GB/month), 85% reduction on a 100GB memory = ~$6100/month savings per tenant
- **Query latency**: smaller graph = smaller index + faster traversals; estimate 30-50% p99 latency reduction
- **Estimated impact**: $1K-$10K/tenant/month at typical SaaS scale
- **Confidence**: medium (storage math is direct; latency math depends on query patterns)

### Bridge 2: engineering toil eliminated

Today, agent memory often grows unbounded because no one wrote the pruning logic. Quarterly manual cleanup is a real engineering tax.

- **Mechanism**: replaces a quarterly cleanup task (4-8 hours of SRE / data-eng time per quarter per deployment) with automatic write-path GC
- **Estimated savings**: 16-32 engineer-hours/year per deployment + reduced incident rate from accidental over-deletion
- **Estimated impact**: $5K-$15K/year in eng-time savings per deployment, plus avoided-incident value
- **Confidence**: medium (eng-time math is rough; incident-cost value is highly variable)

### Bridge 3: user-perceived freshness

A pruned memory is a freshly-curated memory. Queries return current information instead of stale facts that should have been superseded.

- **Mechanism**: removing dead-edge facts means RAG retrievals stop dragging in superseded context
- **CX impact**: model responses are more current, less confusing
- **Estimated impact**: not directly measurable; would show up as fewer "the assistant told me about the old policy" complaints
- **Confidence**: low (no direct CX measurement; folklore says memory freshness matters)

## Best-fit verticals

GC matters most where:

1. **Memory grows unboundedly** (anything with continuous ingestion: CRM, support transcripts, social feeds)
2. **Stale data has cost** (financial / news / time-sensitive verticals where outdated context hurts decisions)
3. **The org pays per-GB storage** (cloud-hosted graph DBs, vector stores)

## Calibration plan

1. **Identify a partner** with a Graphiti / Mem0 / Cognee deployment >100GB and >1M writes/month
2. **Build the integration shim** (Graphiti adapter is the most mature; ~1 engineer-week per `docs/finding-gc-stage4-shim.md`)
3. **Run in shadow mode** for 4 weeks (GC computes collections but does not actually delete)
4. **Measure**: nodes that WOULD have been collected vs hand-audited "should have been collected" set
5. **Cutover** once false-collection rate is verified <1%
6. **Measure post-cutover** (3 months): storage trajectory, query latency, eng-time per quarter on pruning

Total cost: ~6 engineer-weeks across partner + framework provider.

Output: measured storage savings ($X/month), latency improvement (Y ms p99), eng-time savings (Z hours/quarter).

## How this feeds the investment-prioritization tool

The investment tool currently ranks `gc-v0.1.2-fact-only` at +85pp technical lift / 1.0 engineer-week = 85 lift-per-week (rank #1). With this KPI mapping:

- Conservative estimate: $1K/tenant/month savings at 100GB scale
- Optimistic: $10K/tenant/month at 1TB scale  
- ROI: 10-100x in year 1 for any meaningfully-sized deployment
- Plus engineering-toil reduction (16-32 hours/year per deployment)

This is the clearest cost-savings story in the project. The framework's rank #1 fund-now recommendation is grounded in real infrastructure economics.

## Pointers

- GC Stage 3 finding (the technical lift source): `docs/finding-gc-stage3-real-text.md`
- GC Stage 4 integration shim: `docs/finding-gc-stage4-shim.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
