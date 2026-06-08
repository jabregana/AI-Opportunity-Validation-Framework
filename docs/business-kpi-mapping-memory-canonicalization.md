---
type: business-kpi-mapping
opportunity: memory (canonicalization)
date: 2026-06-08
confidence: low
---

# Business KPI mapping: memory canonicalization (schema-alignment proxy)

Bridges the framework's technical lift on the proxy opportunity (entity-extraction F1 +8 to +15pp) to candidate business KPIs an executive can recognize. **Confidence: low.** Numbers below are illustrative order-of-magnitude estimates, not measurements. Calibration plan at the bottom.

## Technical metric

**Entity-extraction F1 lift** for an LLM ingestion pipeline using the proxy as middleware in front of Mem0 / Graphiti / Cognee. Stage 4 finding: +5-7pp lift at substantial-N (n=836 tweets, 125 entities).

## Candidate business KPI bridges

### Bridge 1: per-tenant memory infrastructure cost

If the proxy reduces graph entity-node fragmentation (one canonical per real-world entity instead of many surface-form duplicates), the resulting graph is smaller and queries are faster.

- **Mechanism**: 5-7pp F1 lift translates to ~30-50% fewer duplicate entity nodes (rough; depends on baseline duplication rate)
- **Storage impact**: at 1M facts/tenant, ~30% node reduction = ~30% savings on graph DB storage (Neo4j Aura, Memgraph Cloud, etc)
- **Estimated savings**: $50-$500/tenant/month at typical Neo4j Aura pricing tiers ($65-$700/month base)
- **Confidence**: medium (the storage math is straightforward; the duplication-rate assumption is the unknown)

### Bridge 2: customer-facing retrieval correctness

If the proxy raises F1 on entity extraction, queries for "what does this tenant know about Apple Inc?" stop missing memories stored under "AAPL." This is a user-perceived quality improvement.

- **Mechanism**: 5-7pp F1 lift means ~5-7% of queries that previously missed correct memories now hit them
- **CX impact**: depends entirely on the product surface; for an AI assistant doing per-user recall, 5-7% accuracy on memory lookups can be the difference between "useful" and "unreliable" in user reviews
- **Estimated impact**: highly variable; in B2B SaaS where customers measure agent recall, this could be the lever that moves NPS / churn metrics
- **Confidence**: low (no direct measurement of how recall % translates to user satisfaction in this category)

### Bridge 3: LLM inference cost savings (the original pitch)

The proxy replaces an LLM call per write with a deterministic regex or embedding lookup. This was the original economic case in the proxy's Stage 4 finding.

- **Mechanism**: 1M entity writes/month at $0.005-$0.05/call = $5,000-$50,000/month in LLM inference costs eliminated
- **Realistic estimate**: $5K-$50K/tenant/month for high-volume B2B deployments doing real-time ingestion
- **Confidence**: high (well-measured in the Stage 4 finding's cost analysis; the substantial-N benchmark showed 1000x cost ratio between local 7B + proxy and frontier API at equal accuracy)

## Best-fit verticals

The proxy's value is highest where:

1. **Volume is high** (B2B SaaS with millions of ingestion events: customer support, sales CRM, knowledge management)
2. **Entity ambiguity is real** (financial, clinical, legal verticals where the same entity has many surface forms)
3. **Memory is a product surface, not a backend** (AI assistants users interact with, not data warehouses)

For each: $50K-$500K/year in inference cost savings + materially better retrieval correctness.

## Calibration plan

To convert these estimates to measured business impact:

1. **Identify a design partner** running an LLM-driven ingestion pipeline at >100K writes/month
2. **Measure baseline** (3-4 weeks): current inference cost per million writes, current duplicate-entity rate, current query miss rate on a curated test set
3. **Deploy proxy in shadow mode** (2-3 weeks): proxy runs in parallel, results compared but not yet used
4. **Cutover** (1 week): proxy becomes load-bearing
5. **Measure post-cutover** (4 weeks): same metrics; compute deltas
6. **Translate to $$$**: storage savings + inference savings + (if applicable) NPS / churn delta

Cost to run: ~10 engineer-weeks across the design partner's team and the framework provider, plus monitoring infrastructure.

Output: a real (cost-savings, accuracy-lift) tuple that replaces the order-of-magnitude estimates above with measured values.

## How this feeds the investment-prioritization tool

The investment-prioritization tool currently uses technical lift (+12pp F1) and engineering cost (1 week build) for ROI. With this KPI mapping:

- Default conservative: $50K/tenant/year cost savings at 1M-write tier
- Optimistic: $500K/tenant/year at high-volume vertical
- ROI: at 1 engineer-week build cost (~$10K loaded), 5-50x ROI in year 1 even at conservative tier

That makes the proxy a top-3 investment candidate even before any vertical-specific calibration. **Confidence on the ROI ranking is high; confidence on the absolute $$$ is low.**

## Pointers

- Proxy Stage 4 finding (the technical lift source): `docs/finding-substantial-N-revision.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
- Strategic positioning: `docs/strategic-framing-decision-tool.md`
