---
type: business-kpi-mapping
opportunity: execution policy
date: 2026-06-08
confidence: low
---

# Business KPI mapping: execution policy

Bridges the framework's technical lift on the policy opportunity (`handoff` +19.25pp at 1.32x cost; `plan-execute` +24.25pp at 2.77x cost) to candidate business KPIs. **Confidence: low.**

## Technical metric

**Task completion rate** lift vs single-shot baseline across 400 synthetic tasks (4 task classes). Best 4/4 PASS: `handoff` at +19.25pp completion / 1.32x cost. Higher-completion variants (`plan-execute`, `reflect-loop`) fail UC-POLICY-2 (cost) and UC-POLICY-4 (latency).

## Candidate business KPI bridges

### Bridge 1: task completion as direct KPI (handoff variant)

`handoff` (single-shot, escalate-to-larger-model on failure) is the deployable variant. It adds modest cost (~32% more) for substantial completion lift (~20pp).

- **Mechanism**: most tasks complete in single-shot; the ~30% that fail get escalated to a more capable model
- **At customer-support scale**: 100K tasks/month, +20pp completion = +20K resolutions/month
- **Revenue impact**: at $5/resolution value, +20K = $100K/month avoided cost (~$1.2M/year per deployment)
- **Confidence**: medium (completion-to-revenue translation is product-specific)

### Bridge 2: latency budget compliance (handoff vs multi-step variants)

Agent product UX often has a latency budget (e.g., 5-second response cap). Multi-step variants (ReAct, plan-execute, reflect-loop) regularly blow this budget.

- **Mechanism**: handoff stays at 2 steps p99; reflect-loop takes 9 steps p99 (~5-10x latency)
- **UX impact**: handoff fits in any real-time agent UX; multi-step variants do not
- **Estimated impact**: not directly measurable but determines whether the policy is even SHIPPABLE on a UX-bound surface
- **Confidence**: high (the latency math is direct; the UX constraint is real)

### Bridge 3: deferred upside from plan-execute on cost-tolerant surfaces

On batch / async surfaces (background email summarization, overnight report generation, etc), the multi-step variants' higher completion may justify the cost.

- **Mechanism**: `plan-execute` adds 24pp completion at 2.77x cost; viable when latency does not matter
- **Estimated impact**: same +$1.2M/year-per-deployment shape but only on the subset of surfaces that tolerate async / cost overhead
- **Confidence**: low (most production agents are real-time; the cost-tolerant niche may be small)

## Best-fit verticals

`handoff` (the deployable variant) matters most where:

1. **High task volume** (>100K tasks/month at customer-support shapes)
2. **Quality matters more than per-call latency budget** (an extra ~1 second on 30% of tasks is acceptable)
3. **The org has multiple model tiers available** (handoff routes failures to a larger model)

## Calibration plan

1. **Pick a high-volume task class** with current baseline completion rate measured
2. **Deploy handoff to 10% of traffic** (small model handles single-shot; larger model handles handoff path)
3. **Measure** for 4 weeks: completion rate delta + cost delta + latency p99 delta
4. **Decide promotion based on measured (lift, cost, latency)**

Cost: ~3 engineer-weeks for the routing infrastructure + 4 weeks calibration.

## How this feeds the investment-prioritization tool

The investment tool ranks `policy-v0.1.3-handoff` at +19.25pp / 2.0 weeks = 9.6 lift/week (rank #9, FUND-NOW). With this KPI mapping:

- Conservative: $100K/year at modest task-volume tier
- Optimistic: $1.2M/year per high-volume deployment
- ROI: 5-60x in year 1
- Plus avoided-overspend on the multi-step variants whose latency / cost would have broken UX

The KPI math justifies the FUND-NOW verdict. The DEFER verdicts on `react` and `plan-execute` are also justified: they would over-commit latency budget without a measurable revenue offset on real-time surfaces.

## Pointers

- Policy Stage 2 finding: `docs/finding-policy-stage2-baseline.md`
- Investment-prioritization tool: `experiments/investment_prioritization.py`
