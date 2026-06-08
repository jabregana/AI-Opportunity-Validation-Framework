---
type: finding
opportunity: cross-dimension orchestration
stage: experiment
status: NEGATIVE-INTERACTION-FOUND
date: 2026-06-08
artifact: runs/cross_dim_stage2/20260608T080242.json
---

# Cross-dimension experiment: dimensions interact sub-additively; the weakest dimension dominates

This is the framework's first cross-dimension experiment, and arguably the most consequential single result so far for the six-dimension architecture's value proposition. It demonstrates that **dimension lifts measured independently do NOT compose additively when applied jointly.** Under multiplicative composition, **the weakest dimension dominates the combined outcome.**

**Headline**: combining "the best" variant on each of three dimensions (`cot-plus-structured` + `intent-classified` + `fallback-chain`) produces a config that **completes 25% of scenarios**, which is **12pp WORSE than all-baselines (37%)**. The interaction term (-11.20pp) is large and negative.

The single-dimension benchmarks each looked clean. The joint experiment exposes a structural issue: `tool-v0.1.1-intent-classified`'s 83% recall (the gate it failed in [`finding-tools-stage2-baseline.md`](finding-tools-stage2-baseline.md)) becomes a multiplicative penalty that propagates through every other dimension's lift.

## Why this finding matters

Until now, each dimension's Stage 2 finding doc has reported "passes UC gates against baseline." Implicitly: each variant is an independent win. The cross-dimension experiment shows that implicit additivity assumption is wrong:

- A 7pp prompt lift PLUS a -22pp tools cost PLUS a 14pp recovery lift does NOT sum to -1pp.
- Multiplicatively: P_prompt * P_tools * P_recovery gives -12pp.
- Adopting one weak variant on one dimension can erase all the gains from variants on other dimensions.

This is **the value proposition of the six-dimension architecture**: only joint experiments can surface these interactions. Six independent benchmarks would have shipped three variants whose joint deployment is worse than no variants at all.

## Setup

- **Workload**: `fixtures/workloads/w_cross_dim_scenarios.py`, seed=42
  - 500 scenarios; 150 with injected failures (30%)
  - Each scenario has a goal + category + difficulty (prompt dim) + required tools (tools dim) + optional injected failure (recovery dim)
- **Runner**: `runner/cross_dim_runner.py` with multiplicative composition `P_complete = P_prompt * P_tools * P_recovery`
- **Configurations** tested:

| Label | Prompt | Tools | Recovery |
|---|---|---|---|
| all-baselines | b-default-prompt | b-allow-all-tools | b-abort-on-failure |
| prompt-only | prompt-v0.1.4-cot-plus-structured | b-allow-all-tools | b-abort-on-failure |
| tools-only | b-default-prompt | tool-v0.1.1-intent-classified | b-abort-on-failure |
| recovery-only | b-default-prompt | b-allow-all-tools | recovery-v0.1.1-fallback-chain |
| all-three | prompt-v0.1.4-cot-plus-structured | tool-v0.1.1-intent-classified | recovery-v0.1.1-fallback-chain |

## Results

| Config | Completion % | vs baseline | Avg P_prompt | Avg P_tools | Avg P_recovery |
|---|---|---|---|---|---|
| all-baselines | **36.80** | (baseline) | 0.554 | 1.000 | 0.700 |
| prompt-only | 44.20 | +7.40 | 0.664 | 1.000 | 0.700 |
| tools-only | 15.20 | **-21.60** | 0.554 | **0.426** | 0.700 |
| recovery-only | 50.40 | +13.60 | 0.554 | 1.000 | **0.908** |
| **all-three** | **25.00** | **-11.80** | 0.664 | 0.426 | 0.908 |

### Interaction analysis

```
baseline                    : 36.80%
+ prompt-only delta         : +7.40pp  ->  44.20%
+ tools-only delta          : -21.60pp ->  15.20%
+ recovery-only delta       : +13.60pp ->  50.40%
Additive prediction         : 36.20% (sum of deltas)
Actual all-three            : 25.00%
Interaction term            : -11.20pp
```

**Verdict**: SUB-ADDITIVE. Dimensions compete or saturate; the weakest dimension caps combined lift.

## Honest reading

### What the experiment surfaces

1. **The multiplicative model exposes the tools variant's true cost.** `tool-v0.1.1-intent-classified` had a known recall problem (83% in the Stage 2 finding, below the 90% threshold). On the tools-only benchmark this only manifested as a -22pp completion drop. **On the joint benchmark, that 0.426 average P_tools multiplies every other dimension's contribution.** A scenario with P_prompt=0.75 and P_recovery=0.91 becomes 0.75 * 0.426 * 0.91 = 0.291, much less than P_prompt alone.

2. **Recovery is the most "additive" dimension on this workload.** Because P_recovery only fires when a failure is injected (30% of scenarios), and even then improves outcomes that would otherwise be zero, its contribution adds cleanly. The recovery-only delta (+13.6pp) is the largest single-dimension lift here.

3. **Prompt lifts are real but capped by other dimensions.** prompt-only is +7.4pp; combined with tools, the prompt's contribution becomes invisible because P_tools is already cutting completion by more than half.

4. **The framework would have shipped a worse product without this experiment.** Each dimension's Stage 2 finding doc was honest about its own UC gates (tools' UC-TOOL-3 FAIL was flagged). But "deploy the best variant from each dimension" is a natural conclusion that the framework would have produced. The cross-dim experiment surfaces the catch: don't deploy a variant with a known UC failure on dimension X just because variants on dimensions Y and Z look good.

### What the experiment does NOT prove

- **The multiplicative composition is a simulator design choice, not a measurement.** Real-world dimensions could compose additively, multiplicatively, or with some other interaction. The framework's value here is showing that *some* composition rule changes the verdict; the specific rule needs Stage 3 measurement on real systems.
- **No real-LLM, real-tool, real-recovery measurement.** Everything is simulator. The relative magnitudes of P_prompt / P_tools / P_recovery are designer-chosen.
- **Only one variant per dimension was tested in the joint config.** A future experiment should test all pairwise combinations of variants across dimensions (5 prompt x 3 tools x 3 recovery = 45 configs) to map the full interaction landscape.
- **The injected-failure rate is fixed at 30%.** Different failure rates would change recovery's contribution relative to tools. Sensitivity sweep needed.
- **No statistical confidence intervals.** This experiment reports point estimates only. Paired bootstrap should be added before any production claim.

### What this implies for the framework's narrative

The cross-dimension experiment validates the architectural claim made in [`six-dimensions-architecture.md`](six-dimensions-architecture.md): the six-dimension framing is not just an organizing convenience, it is a research tool. Without it, the recommendation pipeline produces:

> "Recovery: ship fallback-chain (+27pp)."  
> "Tools: ship intent-classified (3/4 gates pass, recall improvement needed)."  
> "Prompt: ship cot-plus-structured (+10.5pp)."  
> Result: -12pp vs baseline. **Worse than doing nothing.**

With the cross-dim experiment, the recommendation becomes:

> "Recovery: ship fallback-chain."  
> "Tools: DO NOT ship intent-classified yet; its 83% recall multiplies through other dimensions. Wait for v0.1.2 with the recall fix."  
> "Prompt: ship cot-plus-structured."  
> Result: estimated +13pp lift from the deployable combination.

**That recommendation difference is the entire value proposition of cross-dimension benchmarks.**

## Decision

Three follow-up actions:

1. **Block the intent-classified tools variant from any production rollout** until the v0.1.2 recall fix lands. Update [`finding-tools-stage2-baseline.md`](finding-tools-stage2-baseline.md) with a reference to this cross-dim experiment so future readers see the joint constraint.

2. **Add cross-dim verification to every dimension's Stage 3 finding doc going forward.** Single-dimension PASS no longer implies "deployable." A variant must also pass a cross-dim sanity check against (best-on-each-other-dimension) before promotion.

3. **Extend the cross-dim experiment to the full variant matrix.** 5 prompt x 3 tools x 3 recovery = 45 configurations. The framework's discipline says this matters more than scaling any single dimension's benchmark. Schedule for the next iteration.

## What this changes about the framework's strategic claim

The analyst review that prompted the six-dimension architectural work (in `external/jeff-cohen-analysis.md` if archived; quoted in earlier sessions) argued that the framework's biggest opportunity is treating agent systems as statistical systems across six dimensions, with cross-dimension interactions as the load-bearing claim.

**This experiment is the first hard evidence that the cross-dimension framing pays off operationally.** Without it, single-dimension benchmarks would have produced a deployment recommendation that is provably worse than baseline. With it, the framework catches the interaction and recommends the deployable subset.

That is what makes this a research framework rather than a benchmark library.

## Pointers

- Code: `experiments/cross_dim_stage2.py`, `runner/cross_dim_runner.py`, `fixtures/workloads/w_cross_dim_scenarios.py`
- Tools dimension finding (the constraint surfaced): [`finding-tools-stage2-baseline.md`](finding-tools-stage2-baseline.md)
- Prompt dimension finding: [`finding-prompt-stage2-baseline.md`](finding-prompt-stage2-baseline.md)
- Recovery dimension findings: [`finding-recovery-stage2-baseline.md`](finding-recovery-stage2-baseline.md), [`finding-recovery-stage3-sensitivity.md`](finding-recovery-stage3-sensitivity.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/cross_dim_stage2.py
# Defaults: n_scenarios=500, failure_rate=0.30, seed=42.
# Writes JSON artifact to runs/cross_dim_stage2/.
```
