---
type: business-kpi-mapping
opportunity: recovery behavior
date: 2026-06-08
confidence: medium
---

# Business KPI mapping: recovery behavior

Bridges the framework's technical lift on the recovery opportunity (`retry-with-backoff` +19.4pp completion; `fallback-chain` +26.6pp completion at <= 1x baseline cost) to candidate business KPIs. **Confidence: medium** (recovery is the dimension with the most generalizable per-failure-kind data).

## Technical metric

**Task completion rate** lift vs abort-on-failure baseline on a 500-scenario workload with 30% failure rate. Best 4/4 PASS: both `retry-with-backoff` (+19.4pp) and `fallback-chain` (+26.6pp), both at 0.90x cost-per-completion (lower because they recover scenarios baseline lost).

The sensitivity Stage 3 finding showed the verdict is ROBUST across 5 plausible probability tables (optimistic, pessimistic, small-model, large-model, hostile).

## Candidate business KPI bridges

### Bridge 1: recovered task volume as direct revenue

Every failed agent task is a potential revenue / cost-savings opportunity lost. Recovery converts these into completions.

- **Mechanism**: +26.6pp completion lift on a 30%-failure workload means ~80% of previously-failed tasks now succeed
- **At customer-support scale**: 100K tasks/month with 30% baseline failure rate = 30K failures; recovery saves 24K of them
- **Revenue impact**: at $5/recovered-resolution, +24K * $5 = $120K/month avoided cost
- **At per-task higher-value verticals** (sales, legal, clinical): $10-$50/recovered-task = $240K-$1.2M/month
- **Confidence**: medium (the per-task-value translation is the unknown)

### Bridge 2: cost-per-correct-completion reduction

Counter-intuitively, recovery REDUCES cost-per-completion (more recovered tasks in the denominator more than offset the retry/fallback overhead).

- **Mechanism**: cost ratio 0.90x baseline = 10% per-completion savings
- **At $5K/M baseline inference cost**: ~$500/M savings + the +27pp completions effectively become near-free since the cost was already incurred
- **Estimated impact**: $5K-$50K/month per deployment on cost-per-completion alone, plus the revenue from the recovered tasks
- **Confidence**: high (well-measured in the Stage 2 finding)

### Bridge 3: SLA / reliability metrics

If the agent product has reliability SLAs, recovery directly improves SLA attainment.

- **Mechanism**: fewer hard-aborts means fewer SLA breaches and fewer service credits
- **CX impact**: error rate is a top-tier reliability metric in B2B contracts
- **Estimated impact**: depends on contract structure; SLA breach credits can be 5-25% of monthly contract value
- **Confidence**: low (contract specifics vary widely)

## Best-fit verticals

Recovery matters most where:

1. **Failure modes are real and common** (LLM-driven workflows often have 10-30% failure rates baseline)
2. **Per-task value is high** (a recovered legal-document analysis is worth more than a recovered casual chat)
3. **The user does not retry on their own** (B2B / async / batch workflows where no human is in the loop to retry)

## Calibration plan

1. **Pick a workflow with measurable failure rate** (an existing agent product probably has these metrics)
2. **Classify recent failures by kind** (tool_error, model_refusal, validation_failure, timeout) using a sample of 500-1000
3. **Calibrate the simulator's probability table** to match the org's failure distribution
4. **Deploy `fallback-chain` to 10-20% of traffic** for 4 weeks
5. **Measure**: recovered-task rate + cost-per-completion delta + p99 latency delta
6. **Promote based on measured (lift, cost, latency)**

Cost: ~5 engineer-weeks (3 for the recovery infrastructure + 2 for calibration).

## How this feeds the investment-prioritization tool

The investment tool ranks `recovery-v0.1.1-fallback-chain` at +26.6pp / 2.0 weeks = 13.3 lift/week (rank #8, FUND-NOW). With this KPI mapping:

- Conservative: $50K/month savings at small-volume tier per deployment ($600K/year)
- Optimistic: $1.2M/month at high-volume vertical ($14M/year)
- ROI: 60-1400x in year 1; this is the second-highest economic case in the matrix after memory lifecycle

This is also the dimension with the highest framework-confidence (Stage 3 ROBUST-PASS across 5 probability tables), so the cost-savings number has the smallest researcher-uncertainty discount.

## Pointers

- Recovery Stage 2 finding: `docs/finding-recovery-stage2-baseline.md`
- Recovery Stage 3 sensitivity: `docs/finding-recovery-stage3-sensitivity.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
