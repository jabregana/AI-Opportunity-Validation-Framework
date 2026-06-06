"""CI/CD edge-case guardrails per experiments.md §6.4.

Three hard policies that the harness enforces around the LORD++ /
non-inferiority machinery:

1. INCONCLUSIVE-is-FAIL on the fast PR tier. Low-N runs caused by upstream
   infra failures must not pass by default.
2. SAFFRON hot-swap recommendation when the rolling 30-day true-null
   proportion exceeds 0.70 — LORD++ starves down-sequence tests when most
   hypotheses fail to reject; SAFFRON adaptively recovers wealth.
3. B-VPREV lookback cap of 14 days for CUPED covariates. Stale baselines
   degrade the variant↔baseline correlation ρ and undermine the variance
   reduction CUPED is supposed to provide.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

MAX_BVPREV_AGE_DAYS = 14
SAFFRON_PI0_THRESHOLD = 0.70


@dataclass
class GateResult:
    name: str
    passed: bool
    reason: str


def inconclusive_is_fail(outcomes: Iterable[str], tier: str) -> GateResult:
    """§6.4.1 — INCONCLUSIVE counts as FAIL for fast PR tier."""
    inconclusive = [o for o in outcomes if o == "INCONCLUSIVE"]
    if tier == "fast" and inconclusive:
        return GateResult(
            "inconclusive_fallback",
            passed=False,
            reason=(
                f"{len(inconclusive)} INCONCLUSIVE outcomes on fast tier "
                "(treated as FAIL — likely under-sampled run)"
            ),
        )
    return GateResult("inconclusive_fallback", passed=True, reason="")


def saffron_hot_swap_recommendation(
    null_proportions_30d: list[float],
    threshold: float = SAFFRON_PI0_THRESHOLD,
) -> GateResult:
    """§6.4.2 — recommend SAFFRON swap if rolling 30d π₀ > threshold."""
    if not null_proportions_30d:
        return GateResult(
            "saffron_swap", passed=True, reason="no 30d history yet"
        )
    rolling_pi0 = sum(null_proportions_30d) / len(null_proportions_30d)
    if rolling_pi0 > threshold:
        return GateResult(
            "saffron_swap",
            passed=False,
            reason=(
                f"rolling 30d π₀ = {rolling_pi0:.3f} > {threshold:.2f}; "
                "swap to SAFFRON for next release cycle"
            ),
        )
    return GateResult(
        "saffron_swap",
        passed=True,
        reason=f"rolling 30d π₀ = {rolling_pi0:.3f}",
    )


def bvprev_age_ok(
    bvprev_artifact_path: str | Path,
    now: datetime | None = None,
    max_age_days: int = MAX_BVPREV_AGE_DAYS,
) -> GateResult:
    """§6.4.3 — reject CUPED covariates from baselines older than max_age_days.

    `now` is injectable for testing.
    """
    path = Path(bvprev_artifact_path)
    if not path.exists():
        return GateResult(
            "bvprev_age",
            passed=False,
            reason=f"B-VPREV artifact not found at {path}",
        )
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return GateResult(
            "bvprev_age",
            passed=False,
            reason=f"B-VPREV artifact unparseable: {exc}",
        )
    # Support both the legacy flat schema and the §6.1 three-block schema.
    ts_str = (
        payload.get("artifact_metadata", {}).get("timestamp_utc")
        or payload.get("timestamp_utc")
    )
    if not ts_str:
        return GateResult(
            "bvprev_age",
            passed=False,
            reason="B-VPREV artifact missing timestamp_utc",
        )
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    current = now if now is not None else datetime.now(timezone.utc)
    age = current - ts
    if age > timedelta(days=max_age_days):
        return GateResult(
            "bvprev_age",
            passed=False,
            reason=(
                f"B-VPREV is {age.days}d old > {max_age_days}d cap; "
                "CUPED disabled — fall back to unadjusted variance"
            ),
        )
    return GateResult(
        "bvprev_age", passed=True, reason=f"B-VPREV age = {age.days}d"
    )
