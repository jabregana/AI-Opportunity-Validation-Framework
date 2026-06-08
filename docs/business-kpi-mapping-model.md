---
type: business-kpi-mapping
opportunity: model
date: 2026-06-08
confidence: high
---

# Business KPI mapping: model selection

Bridges the framework's model-dimension capability (14-model ladder across 5 providers) to candidate business KPIs. **Confidence: high** (this is the best-studied dimension in commercial AI today; the framework's contribution is statistical-rigor on the comparison, not the comparison itself).

## Technical metric

**Quality x cost x latency** across the multi-model ladder (`experiments/ladder_sweep_real_data.py`). The proxy case study measured 14 models from 5 providers on the schema-alignment task; the substantial-N finding showed free local 7B ties gpt-4o at the workload's ceiling.

## Candidate business KPI bridges

### Bridge 1: 1000x inference cost reduction at equal quality

The proxy + local-7B combination demonstrated equal accuracy to gpt-4o at ~1000x lower per-call cost.

- **Mechanism**: replace frontier API calls with local model + proxy preprocessing
- **Cost math**: gpt-4o at ~$5/M tokens; self-hosted 7B at ~$0.005/M (electricity / compute)
- **At 10M calls/month**: $50K/month vs $50/month = $50K/month savings
- **At 100M calls/month**: $500K/month savings ($6M/year)
- **Confidence**: high (well-measured in the proxy's Stage 4 finding)

### Bridge 2: model-size-aware routing

Smaller models work for some task classes; larger models needed for others. The framework's multi-model ladder data lets an org pick the smallest model that passes its quality bar per task class.

- **Mechanism**: route easy tasks (classification, extraction) to small model; hard tasks (reasoning, code) to larger model
- **Estimated savings**: 50-80% per-call cost reduction at constant quality
- **At 100M-call scale**: $250K-$400K/month savings
- **Confidence**: high (well-measured by industry routing products like Martian, RouteLLM)

### Bridge 3: vendor lock-in reduction

Multi-model evaluation makes vendor switching cheap. An org locked into one provider pays "captive customer" pricing premiums.

- **Mechanism**: framework's multi-provider ladder demonstrates the work is portable
- **Estimated impact**: 10-30% negotiation leverage on enterprise API contracts
- **Confidence**: medium (negotiation impact varies by contract size)

## Best-fit verticals

Model selection optimization matters most where:

1. **Inference cost is a meaningful line item** (any LLM deployment at >$10K/month)
2. **Task class diversity exists** (different tasks benefit from different model sizes)
3. **The org has the ops capacity to self-host or multi-source** (rules out many startups)

## Calibration plan (mostly already done)

The framework has already calibrated this at the proxy case study scope. Generalizing requires:

1. **Inventory the org's current task classes** (categorize by difficulty / required capability)
2. **Run the multi-model ladder against each class** (the framework's `ladder_sweep_real_data.py` already does this)
3. **Identify the smallest model that passes the quality bar per class**
4. **Route accordingly**

Cost: ~4 engineer-weeks for the routing infrastructure + 2-4 weeks of class-specific calibration.

## How this feeds the investment-prioritization tool

The model dimension is currently outside the investment tool's variant matrix (it ships as the multi-model ladder, not as discrete variants). With this KPI mapping:

- Conservative: $50K/year per task class via right-sizing
- Optimistic: $6M/year via local-deployment + proxy at high volume
- ROI: 50-6000x in year 1

The model dimension is the largest single economic lever in the project. The proxy case study is in part a demonstration of the cost-saving math; the framework should surface this prominently to enterprise audiences.

## Pointers

- Multi-model ladder runner: `experiments/ladder_sweep_real_data.py`
- Proxy substantial-N finding (the cost-savings demonstration): `docs/finding-substantial-N-revision.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
