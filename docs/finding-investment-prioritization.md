---
type: finding
opportunity: framework positioning
stage: deliverable
status: DECISION-TOOL-OUTPUT-SHIPPED
date: 2026-06-08
artifact: runs/investment_prioritization/20260608T091037.json
---

# Investment-prioritization tool: framework now outputs ranked FUND-NOW recommendations

This finding documents the first execution of the **investment-prioritization tool** (proposal 3 from [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)). The tool synthesizes per-variant lift data from the dimension-specific Stage 2/3 findings with per-variant engineering-cost estimates (`runner/variant_costs.py`) and cross-dim interaction caveats. **Output is a ranked list of variants by lift-per-engineer-week with explicit FUND-NOW / FUND-Q+1 / DEFER / DO-NOT-BUILD verdicts.**

**Headline**: this is the framework's first answer to the executive's "what should I spend my next quarter on?" question. 11 variants flagged FUND-NOW (high ROI, low effort); 3 flagged DO-NOT-BUILD; total commitment for the FUND-NOW set is 11.5 engineer-weeks.

## What the tool does

Input:
- Per-variant lift data from the dimension finding docs (`VARIANT_LIFTS` in `experiments/investment_prioritization.py`)
- Per-variant engineering cost estimates (`runner/variant_costs.py`, 32 variants registered)
- Cross-dim interaction notes (folded into the lift data)

Computation:
- `lift_per_engineer_week = lift_pp / engineer_weeks`
- Verdict thresholds:
  - **FUND-NOW**: lift >= +5pp AND engineer_weeks <= 2 (high ROI, low effort)
  - **FUND-Q+1**: lift >= +10pp AND engineer_weeks <= 5
  - **DEFER**: positive lift but fails the above thresholds
  - **DO-NOT-BUILD**: lift <= 0 OR cross-dim says single-dim lift does not survive
  - **INSUFFICIENT-DATA**: no engineering-cost estimate registered

Output:
- Ranked list (verdict bucket first, then lift-per-week within bucket)
- Per-variant cross-dim caveats
- Aggregated FUND-NOW report with total engineer-week commitment

## First run: results

| Rank | Verdict | Lift | Eng-wk | Lift/wk | Variant |
|---|---|---|---|---|---|
| 1 | FUND-NOW | +85.0pp | 1.0 | 85.0 | gc-v0.1.2-fact-only |
| 2 | FUND-NOW | +8.5pp | 0.2 | 42.5 | prompt-v0.1.0-cot |
| 3 | FUND-NOW | +12.0pp | 0.5 | 24.0 | embed-proxy-v0.3.1 |
| 4 | FUND-NOW | +6.5pp | 0.3 | 21.7 | prompt-v0.1.2-few-shot-1 |
| 5 | FUND-NOW | +10.5pp | 0.5 | 21.0 | prompt-v0.1.4-cot-plus-structured |
| 6 | FUND-NOW | +10.0pp | 0.5 | 20.0 | prompt-v0.1.3-few-shot-3 |
| 7 | FUND-NOW | +19.4pp | 1.0 | 19.4 | recovery-v0.1.0-retry-with-backoff |
| 8 | FUND-NOW | +26.6pp | 2.0 | 13.3 | recovery-v0.1.1-fallback-chain |
| 9 | FUND-NOW | +19.2pp | 2.0 | 9.6 | policy-v0.1.3-handoff |
| 10 | FUND-NOW | +13.5pp | 1.5 | 9.0 | embed-proxy-v0.5.3-singleton-aware |
| 11 | FUND-NOW | +13.5pp | 2.0 | 6.8 | embed-proxy-v0.5.7-mt-ann |
| 12 | FUND-Q+1 | +28.5pp | 5.0 | 5.7 | policy-v0.1.2-reflect-loop |
| 13 | DEFER | +20.5pp | 3.0 | 6.8 | policy-v0.1.0-react |
| 14 | DEFER | +24.2pp | 4.0 | 6.1 | policy-v0.1.1-plan-execute |
| 15 | DEFER | +2.5pp | 0.5 | 5.0 | prompt-v0.1.1-direct-structured |
| 16 | **DO-NOT-BUILD** | +8.0pp | 2.0 | 4.0 | tool-v0.1.1-intent-classified |
| 17 | **DO-NOT-BUILD** | +4.3pp | 3.0 | 1.4 | tool-v0.1.2-intent-plus-helper |
| 18 | **DO-NOT-BUILD** | -46.7pp | 0.5 | 0.0 | tool-v0.1.0-budget-bucketed |

Notable: **all three tools variants are flagged DO-NOT-BUILD** despite v0.1.1 and v0.1.2 showing positive single-dim lift. The cross-dim caveat overrides the single-dim verdict. This is exactly the value-add the analyst's review named.

### Verdict distribution

| Verdict | Count | Total eng-weeks |
|---|---|---|
| FUND-NOW | 11 | 11.5 |
| FUND-Q+1 | 1 | 5.0 |
| DEFER | 3 | 7.5 |
| DO-NOT-BUILD | 3 | (n/a, do not build) |

The FUND-NOW set commits 11.5 engineer-weeks (~3 engineer-months) for 11 variants. Several can be parallelized across engineers; the critical path is probably the recovery + policy work (4 weeks combined).

## Honest reading

### What this earns

- **The framework now produces a deliverable an executive can act on.** The output is a ranked list with a clear verdict, build cost, and ROI. The analyst's "decision-making framework" framing now has a concrete artifact.
- **Cross-dim interactions are first-class.** The tool explicitly downgrades single-dim winners that lose in cross-dim composition. tool-v0.1.1 (3/4 single-dim gates pass) is correctly flagged DO-NOT-BUILD because the cross-dim matrix showed it makes joint deployments worse.
- **The "rank by ROI not by raw lift" framing surfaces cheap wins.** `prompt-v0.1.0-cot` at +8.5pp / 0.2 weeks ranks #2 despite having less lift than `policy-v0.1.2-reflect-loop` at +28.5pp / 5 weeks (which ranks #12). For an engineering-budget-constrained team, the framework recommends the cheap-and-good wins first.
- **The single-line-per-variant format is what executives consume.** Each row is one sentence: "ship X to lift Y by Zpp at N engineer-weeks." That fits in a quarterly planning doc.

### What this finding does NOT earn

- **No real-LLM validation of the lift numbers.** Every `lift_pp` value in `VARIANT_LIFTS` comes from simulator outputs. The Stage 3 real-LLM run (with phi3:mini via Ollama) verifies the driver works but does not validate the simulator's quantitative predictions. Without that validation, "+10.5pp on cot-plus-structured" is the simulator's claim, not a measured outcome.
- **No business-KPI overlay.** Lifts are reported in % completion, store-reduction, etc. No mapping to revenue / conversion / deflection / cost savings. This is proposal 2 from the strategic doc; still deferred.
- **Engineering-cost estimates are researcher-guessed.** `runner/variant_costs.py` is honest about this ("Confidence: medium"). A real org should override these with their own retrospective audit of how long similar work took.
- **Bootstrap CIs are not folded in.** The cost-weighted matrix experiment produced 95% CIs on each cross-dim configuration's completion rate. The investment-prioritization tool currently uses single-dim lift point estimates without CIs. Should be added next iteration.
- **The FUND-NOW total of 11 variants does not compose linearly.** The cross-dim finding showed that combining N "best" variants produces a joint config that may be worse than baseline. The framework's actual deployment recommendation (from the cross-dim matrix) is a SUBSET: cot-plus-structured + b-allow-all-tools + fallback-chain. The investment-prioritization tool currently shows ALL variants worth funding individually; a smarter version would surface the deployable joint subsets.

### Why this finding is consequential

For the project's narrative: this is the **first artifact that maps the analyst's "mechanism -> statistical effect -> engineering cost -> business value" framework**. Three of the four layers are now connected:

- Mechanism: variant ABCs
- Statistical effect: lift % from finding docs
- Engineering cost: `runner/variant_costs.py`

Business value remains a researcher-guessed translation; the strategic doc's proposal 2 (business-KPI mapping per opportunity) is the natural next step.

## Comparison: how the framework's recommendation has evolved across this project

| Stage | What the framework recommended |
|---|---|
| Single-dim Stage 2 findings | Ship a tools variant (3/4 gates pass) |
| Cross-dim full matrix | Ship cot-plus-structured + b-allow-all-tools + fallback-chain; do NOT ship any tools variant |
| Investment prioritization | Same deployment recommendation, plus 11-variant FUND-NOW list with eng-week budgets and lift-per-week ranking |

The recommendation has not flipped; it has gained progressively more decision-relevant context: cross-dim said "what to ship," cost-weighted matrix added "with what statistical confidence at what runtime cost," and the investment tool now adds "for what engineering-week commitment and ROI."

## Decision

Ship the investment-prioritization tool as the framework's executive-facing output. The single-dim finding docs remain the research output; this is the planning-meeting output.

Three follow-ups:

1. **Build proposal 2 (business-KPI mapping)**: bridges to revenue / conversion / deflection. Per opportunity.
2. **Fold bootstrap CIs into the prioritization**: currently uses point estimates; should use CI lower bound to be conservative.
3. **Add deployable-subset detection**: currently lists individual variants worth funding; should also surface joint subsets that the cross-dim matrix says deploy well together.

## Pointers

- Code: `experiments/investment_prioritization.py`, `runner/variant_costs.py`
- Source findings:
  - [`finding-cross-dim-cost-weighted.md`](finding-cross-dim-cost-weighted.md) (refined recommendation + CIs)
  - [`finding-cross-dim-full-matrix.md`](finding-cross-dim-full-matrix.md) (interaction effects)
  - Per-dimension Stage 2 findings (lift data sources)
- Strategic positioning: [`strategic-framing-decision-tool.md`](strategic-framing-decision-tool.md)
- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)

## Reproduce

```sh
.venv/bin/python experiments/investment_prioritization.py
# Reads VARIANT_LIFTS from this file + variant_costs.py.
# Outputs ranked recommendation table + FUND-NOW summary.
```
