---
type: business-kpi-mapping
opportunity: prompt
date: 2026-06-08
confidence: medium
---

# Business KPI mapping: prompt strategies

Bridges the framework's technical lift on prompt strategy comparison (`cot-plus-structured` +10.5pp completion at 1.32x cost) to candidate business KPIs. **Confidence: medium** (cost-quality is the best-measured layer of the framework).

## Technical metric

**Task completion rate** lift vs default prompt across a 400-task synthetic workload (5 categories: reasoning, extraction, classification, retrieval, code). Best variant: `cot-plus-structured` at +10.5pp / 1.32x cost ratio.

## Candidate business KPI bridges

### Bridge 1: task completion rate as direct KPI

Many agent products HAVE task completion as a primary product metric (customer-support agents close tickets, sales agents log opportunities, etc).

- **Mechanism**: +10.5pp completion lift means 10.5 of every 100 previously-failed tasks now succeed
- **Direct impact**: on a 100K-task-per-month deployment, +10.5K successful tasks/month
- **Revenue impact**: depends on cost-per-task and value-per-success; for customer support at $5 avoided-human-handoff per AI-resolved ticket, +10.5K resolutions = $52K/month avoided cost
- **Estimated impact**: $50K-$500K/year per deployment, scaling with volume
- **Confidence**: medium (the multiplier from completion to $$$ varies wildly by category)

### Bridge 2: agent product CX (retry rate as a proxy)

A failed agent task usually leads to a retry, a human handoff, or user abandonment. All are measurable in product analytics.

- **Mechanism**: +10.5pp completion means -10.5pp retry/abandon rate
- **CX impact**: reduces "your AI did not understand" friction
- **Estimated impact**: highly product-specific; in B2C contexts, 10pp reduction in abandonment can move funnel-conversion metrics by 1-3pp
- **Confidence**: low (no direct measurement; product-team estimate)

### Bridge 3: per-call cost discipline

The framework's Pareto frontier surfaces that `cot-plus-structured` beats `few-shot-3` on cost at statistically-equal completion. Adopting the right variant saves real money per call.

- **Mechanism**: switching from `few-shot-3` (2.09x baseline cost) to `cot-plus-structured` (1.32x baseline cost) saves ~36% per call at equal completion
- **At 1M calls/month**: at $5K/M baseline cost, switch saves $1800/month (~$22K/year)
- **At 100M calls/month**: $180K/month savings ($2.2M/year)
- **Confidence**: high (well-measured by the cost-weighted matrix experiment)

## Best-fit verticals

Prompt-strategy comparison matters most where:

1. **Volume is high enough that 30% cost savings is material** (>1M calls/month)
2. **Completion rate is a tracked product KPI** (customer support, agent-assist, vertical AI agents)
3. **The org has multiple model tiers** (the cost wedge gets bigger when paired with a model-tier strategy)

## Calibration plan

1. **Pick the highest-volume task class in the org's current production agent**
2. **Add A/B testing infrastructure** (most analytics platforms support; LaunchDarkly, Statsig, in-house)
3. **Deploy `cot-plus-structured` to 10% of traffic** for 4 weeks
4. **Measure**: completion rate delta + cost-per-call delta
5. **Compute**: $/year savings + completion-rate lift
6. **Decide promotion to 100% based on measured CI vs +5pp threshold**

Cost to run: ~2 engineer-weeks for A/B setup + ongoing measurement.

Output: measured (completion-rate-lift, cost-delta) tuple, calibrated to this org's actual task mix.

## How this feeds the investment-prioritization tool

The investment tool ranks `prompt-v0.1.4-cot-plus-structured` at +10.5pp / 0.5 weeks = 21 lift/week (rank #5). With this KPI mapping:

- Conservative: $20K/year savings at 1M-call scale per task class
- Optimistic: $2M/year savings at 100M-call scale across multiple task classes
- ROI: 40-4000x in year 1; this is the most-economically-defensible variant in the matrix

## Pointers

- Prompt Stage 2 finding (the technical lift source): `docs/finding-prompt-stage2-baseline.md`
- Cost-weighted matrix (Pareto frontier with CIs): `docs/finding-cross-dim-cost-weighted.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
