"""Investment-prioritization tool.

Synthesizes the cost-weighted cross-dim matrix output (per-variant
completion lift + token cost) with the per-variant engineering cost
estimates (from runner/variant_costs.py) into a single ranked
investment report.

Output answers the executive's question:

  "I have N engineering-quarters to spend on agent improvements.
   Where should I spend them?"

For each variant, computes:

  - lift_pp                   : completion-rate lift vs baseline
  - engineer_weeks            : one-time build effort
  - lift_per_engineer_week    : ROI proxy (higher = better)
  - cost_per_million_calls    : runtime cost
  - verdict                   : FUND-NOW | FUND-Q+1 | DEFER | DO-NOT-BUILD

Verdict thresholds:

  FUND-NOW       : lift >= +5pp AND engineer_weeks <= 2 (high ROI, low effort)
  FUND-Q+1       : lift >= +10pp AND engineer_weeks <= 5 (medium ROI, deferred slot)
  DEFER          : lift > 0 (positive but not high enough ROI)
  DO-NOT-BUILD   : lift <= 0 (negative or zero contribution)

These thresholds are tunable per the user's org. The first version
uses conservative defaults.

This is the deliverable the analyst review named
(`docs/strategic-framing-decision-tool.md` proposal 3).
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.variant_costs import get_build_cost


# Lift data per variant: drawn from the dimension-specific Stage 2
# finding docs (completion-rate lift vs baseline of that dimension).
# These are point estimates from the simulator; bootstrap CIs from
# the cost-weighted matrix should be folded in next iteration.
VARIANT_LIFTS: dict[str, dict] = {
    # ---- Memory canonicalization (proxy case study) ----
    # From the Stage 4 substantial-N finding: proxy variants lift
    # entity-extraction LLM accuracy 8-15pp on average.
    "embed-proxy-v0.3.1": {
        "lift_pp": 12.0,
        "metric": "entity-extraction F1",
        "baseline": "no-proxy",
        "source": "finding-substantial-N-revision.md",
    },
    "embed-proxy-v0.5.3-singleton-aware": {
        "lift_pp": 13.5,
        "metric": "entity-extraction F1 (multi-tenant)",
        "baseline": "no-proxy",
        "source": "finding-substantial-N-revision.md",
    },
    "embed-proxy-v0.5.7-mt-ann": {
        "lift_pp": 13.5,
        "metric": "entity-extraction F1 (multi-tenant, ANN scale)",
        "baseline": "no-proxy",
        "source": "finding-substantial-N-revision.md",
    },

    # ---- Memory lifecycle (graph GC case study) ----
    "gc-v0.1.2-fact-only": {
        "lift_pp": 84.96,
        "metric": "store-size reduction",
        "baseline": "b-raw-no-gc",
        "source": "finding-gc-stage3-real-text.md",
    },

    # ---- Prompt dimension ----
    "prompt-v0.1.0-cot": {
        "lift_pp": 8.5,
        "metric": "completion rate",
        "baseline": "b-default-prompt",
        "source": "finding-prompt-stage2-baseline.md",
    },
    "prompt-v0.1.1-direct-structured": {
        "lift_pp": 2.5,
        "metric": "completion rate",
        "baseline": "b-default-prompt",
        "source": "finding-prompt-stage2-baseline.md",
    },
    "prompt-v0.1.2-few-shot-1": {
        "lift_pp": 6.5,
        "metric": "completion rate",
        "baseline": "b-default-prompt",
        "source": "finding-prompt-stage2-baseline.md",
    },
    "prompt-v0.1.3-few-shot-3": {
        "lift_pp": 10.0,
        "metric": "completion rate",
        "baseline": "b-default-prompt",
        "source": "finding-prompt-stage2-baseline.md",
    },
    "prompt-v0.1.4-cot-plus-structured": {
        "lift_pp": 10.5,
        "metric": "completion rate",
        "baseline": "b-default-prompt",
        "source": "finding-prompt-stage2-baseline.md",
    },

    # ---- Tools dimension ----
    # Single-dim lifts (NOTE: cross-dim says these are negative; see
    # interaction_note field below for the cross-dim multiplier).
    "tool-v0.1.0-budget-bucketed": {
        "lift_pp": -46.67,
        "metric": "completion rate",
        "baseline": "b-allow-all-tools",
        "source": "finding-tools-stage2-baseline.md",
        "interaction_note": "Negative even single-dim; cross-dim confirms.",
    },
    "tool-v0.1.1-intent-classified": {
        "lift_pp": 8.00,
        "metric": "completion rate (single-dim)",
        "baseline": "b-allow-all-tools",
        "source": "finding-tools-stage2-baseline.md",
        "interaction_note": "Cross-dim LOSES 11pp vs baseline due to 84% recall multiplier; do not deploy until v0.2.0.",
    },
    "tool-v0.1.2-intent-plus-helper": {
        "lift_pp": 4.33,
        "metric": "completion rate (single-dim)",
        "baseline": "b-allow-all-tools",
        "source": "finding-tools-v0.1.2-revision.md",
        "interaction_note": "Cross-dim still loses; v0.1.3 with embedding classifier needed.",
    },

    # ---- Policy dimension ----
    "policy-v0.1.0-react": {
        "lift_pp": 20.5,
        "metric": "completion rate",
        "baseline": "b-single-shot-policy",
        "source": "finding-policy-stage2-baseline.md",
        "interaction_note": "Lift real but fails UC-POLICY-2 (cost) and UC-POLICY-4 (latency); 6.24x more steps than baseline.",
    },
    "policy-v0.1.1-plan-execute": {
        "lift_pp": 24.25,
        "metric": "completion rate",
        "baseline": "b-single-shot-policy",
        "source": "finding-policy-stage2-baseline.md",
        "interaction_note": "Fails UC-POLICY-2 (2.77x cost). Conditional ship for cost-tolerant deployments.",
    },
    "policy-v0.1.2-reflect-loop": {
        "lift_pp": 28.5,
        "metric": "completion rate",
        "baseline": "b-single-shot-policy",
        "source": "finding-policy-stage2-baseline.md",
        "interaction_note": "Pareto-dominated by plan-execute. Reflect-loop wins only on needs_reflection tasks (74%).",
    },
    "policy-v0.1.3-handoff": {
        "lift_pp": 19.25,
        "metric": "completion rate",
        "baseline": "b-single-shot-policy",
        "source": "finding-policy-stage2-baseline.md",
    },

    # ---- Recovery dimension ----
    "recovery-v0.1.0-retry-with-backoff": {
        "lift_pp": 19.40,
        "metric": "completion rate",
        "baseline": "b-abort-on-failure",
        "source": "finding-recovery-stage2-baseline.md",
    },
    "recovery-v0.1.1-fallback-chain": {
        "lift_pp": 26.60,
        "metric": "completion rate",
        "baseline": "b-abort-on-failure",
        "source": "finding-recovery-stage2-baseline.md",
    },
}


@dataclass
class InvestmentRecommendation:
    variant_name: str
    dimension: str
    lift_pp: float
    metric: str
    engineer_weeks: float | None
    ongoing_quarterly_weeks: float | None
    infra_cost_per_million_calls_usd: float | None
    lift_per_engineer_week: float | None
    verdict: str
    notes: list[str] = field(default_factory=list)


def _dimension_of(variant_name: str) -> str:
    if "embed-proxy" in variant_name or variant_name == "b-raw-identity":
        return "memory (canonicalization)"
    if "gc-" in variant_name or "b-raw-no-gc" in variant_name:
        return "memory (lifecycle)"
    if "prompt-" in variant_name or variant_name == "b-default-prompt":
        return "prompt"
    if "tool-" in variant_name or variant_name == "b-allow-all-tools":
        return "tools"
    if "policy-" in variant_name or "single-shot" in variant_name:
        return "execution policy"
    if "recovery-" in variant_name or "abort-on-failure" in variant_name:
        return "recovery"
    return "unknown"


def _verdict(
    lift_pp: float,
    engineer_weeks: float | None,
    interaction_note: str | None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if interaction_note:
        notes.append(f"Cross-dim caveat: {interaction_note}")

    if lift_pp <= 0:
        return "DO-NOT-BUILD", notes
    if engineer_weeks is None:
        return "INSUFFICIENT-DATA", notes + ["Engineering-cost estimate unknown."]

    # If interaction_note flags a negative cross-dim effect, downgrade
    if interaction_note and (
        "do not deploy" in interaction_note.lower()
        or "cross-dim still loses" in interaction_note.lower()
    ):
        return "DO-NOT-BUILD", notes + ["Cross-dim says single-dim lift does not survive."]

    if interaction_note and ("conditional" in interaction_note.lower()
                             or "fails uc" in interaction_note.lower()):
        return "DEFER", notes

    if lift_pp >= 5.0 and engineer_weeks <= 2.0:
        return "FUND-NOW", notes
    if lift_pp >= 10.0 and engineer_weeks <= 5.0:
        return "FUND-Q+1", notes
    if lift_pp > 0:
        return "DEFER", notes
    return "DO-NOT-BUILD", notes


def compute_recommendations() -> list[InvestmentRecommendation]:
    recs: list[InvestmentRecommendation] = []
    for variant_name, lift_data in VARIANT_LIFTS.items():
        cost = get_build_cost(variant_name)
        eng_weeks = cost.get("engineer_weeks")
        lift = lift_data["lift_pp"]
        interaction = lift_data.get("interaction_note")
        if eng_weeks is not None and eng_weeks > 0:
            lift_per_week = lift / eng_weeks if lift > 0 else 0.0
        else:
            lift_per_week = None

        verdict, notes = _verdict(lift, eng_weeks, interaction)
        recs.append(InvestmentRecommendation(
            variant_name=variant_name,
            dimension=_dimension_of(variant_name),
            lift_pp=lift,
            metric=lift_data["metric"],
            engineer_weeks=eng_weeks,
            ongoing_quarterly_weeks=cost.get("ongoing_quarterly_weeks"),
            infra_cost_per_million_calls_usd=cost.get(
                "infra_cost_per_million_calls_usd"),
            lift_per_engineer_week=lift_per_week,
            verdict=verdict,
            notes=notes,
        ))
    return recs


def main():
    p = argparse.ArgumentParser(prog="investment-prioritization")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    recs = compute_recommendations()

    # Sort: FUND-NOW first, then FUND-Q+1, then DEFER, then DO-NOT-BUILD;
    # within each verdict bucket, sort by lift_per_engineer_week desc
    verdict_order = {
        "FUND-NOW": 0, "FUND-Q+1": 1, "DEFER": 2,
        "INSUFFICIENT-DATA": 3, "DO-NOT-BUILD": 4,
    }
    recs.sort(key=lambda r: (
        verdict_order.get(r.verdict, 99),
        -(r.lift_per_engineer_week or 0.0),
    ))

    print("=" * 96)
    print("INVESTMENT PRIORITIZATION REPORT")
    print("=" * 96)
    print(f"{'rank':>4} {'verdict':<16} {'lift':>7} "
          f"{'eng-wk':>6} {'lift/wk':>8} {'variant':<40}")
    for i, r in enumerate(recs):
        lift_str = f"{r.lift_pp:+.1f}pp"
        eng_str = f"{r.engineer_weeks:.1f}" if r.engineer_weeks is not None else "?"
        ratio_str = (f"{r.lift_per_engineer_week:.1f}"
                     if r.lift_per_engineer_week is not None else "?")
        print(f"{i+1:>4} {r.verdict:<16} {lift_str:>7} "
              f"{eng_str:>6} {ratio_str:>8} {r.variant_name:<40}")
    print()

    # Per-verdict summary
    by_verdict: dict[str, int] = {}
    for r in recs:
        by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
    print("=" * 96)
    print("Summary by verdict")
    print("=" * 96)
    for v in ["FUND-NOW", "FUND-Q+1", "DEFER", "INSUFFICIENT-DATA",
              "DO-NOT-BUILD"]:
        if v in by_verdict:
            print(f"  {v:<20}  {by_verdict[v]} variant(s)")
    print()

    # Notes
    print("=" * 96)
    print("Cross-dim and other caveats")
    print("=" * 96)
    for r in recs:
        if r.notes:
            print(f"  {r.variant_name}")
            for note in r.notes:
                print(f"    - {note}")
    print()

    # FUND-NOW list (the actionable output)
    fund_now = [r for r in recs if r.verdict == "FUND-NOW"]
    if fund_now:
        print("=" * 96)
        print("RECOMMENDED INVESTMENT: FUND NOW (lift >= +5pp, build <= 2 eng-weeks)")
        print("=" * 96)
        total_weeks = 0.0
        total_lift = 0.0
        for r in fund_now:
            print(f"  {r.variant_name}")
            print(f"    Dimension: {r.dimension}")
            print(f"    Lift:      {r.lift_pp:+.1f}pp on {r.metric}")
            print(f"    Build:     {r.engineer_weeks} engineer-weeks")
            print(f"    Ongoing:   {r.ongoing_quarterly_weeks} weeks/quarter")
            print(f"    Infra:     ${r.infra_cost_per_million_calls_usd}/M calls")
            print()
            total_weeks += r.engineer_weeks or 0
            total_lift += r.lift_pp
        print(f"Total commitment: {total_weeks} engineer-weeks build, "
              f"{sum((r.ongoing_quarterly_weeks or 0) for r in fund_now)} weeks/quarter ongoing")
        print(f"Total nominal lift (NOTE: single-dim sum, not joint): "
              f"+{total_lift:.1f}pp")
        print()
        print("CAVEAT: nominal lift sum is single-dimension. The joint lift "
              "under multiplicative composition is documented in")
        print("docs/finding-cross-dim-cost-weighted.md "
              "(joint config ~60% completion, +23pp vs all-baselines).")

    if args.out:
        out_path = Path(args.out)
    else:
        ts = time.strftime("%Y%m%dT%H%M%S")
        out_dir = ROOT / "runs" / "investment_prioritization"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"

    artifact = {
        "experiment": "investment prioritization",
        "n_variants": len(recs),
        "recommendations": [
            {
                "variant_name": r.variant_name,
                "dimension": r.dimension,
                "lift_pp": r.lift_pp,
                "metric": r.metric,
                "engineer_weeks": r.engineer_weeks,
                "ongoing_quarterly_weeks": r.ongoing_quarterly_weeks,
                "infra_cost_per_million_calls_usd": r.infra_cost_per_million_calls_usd,
                "lift_per_engineer_week": r.lift_per_engineer_week,
                "verdict": r.verdict,
                "notes": r.notes,
            }
            for r in recs
        ],
        "by_verdict": by_verdict,
        "fund_now_count": len(fund_now),
        "fund_now_total_weeks": sum(
            (r.engineer_weeks or 0) for r in fund_now
        ),
    }
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"Artifact: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
