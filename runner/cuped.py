"""CUPED variance reduction (Deng, Xu, Kohavi, Walker, KDD 2013).

Given paired (x_variant, x_baseline) values for the same items, where
x_baseline is a pre-experiment covariate (the per-item metric value from
B-VPREV, the last green commit):

    θ = Cov(X_variant, X_baseline) / Var(X_baseline)
    X_cuped[i] = X_variant[i] − θ · (X_baseline[i] − mean(X_baseline))

Variance reduction: Var(X_cuped) / Var(X_variant) = 1 − ρ² where ρ is the
Pearson correlation between variant and baseline. For file-memory systems
tracking structured items across versions ρ routinely exceeds 0.55,
typically delivering the 20–40% σ² reduction that offsets the §5.3
non-inferiority N inflation.

CUPED is only valid when the baseline was measured *before* the variant
ran. For the harness this means the B-VPREV artifact must already exist on
disk and not have been re-computed against the current variant.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class CupedResult:
    theta: float
    rho: float
    variance_reduction: float  # ρ² — fraction of σ² removed (e.g., 0.30 = "30% reduction")
    adjusted_values: list[float]
    n: int


def cuped_adjust(
    x_variant: list[float], x_baseline: list[float]
) -> CupedResult:
    """Adjust per-item variant metric using paired baseline covariate."""
    if len(x_variant) != len(x_baseline):
        raise ValueError(
            f"variant ({len(x_variant)}) and baseline ({len(x_baseline)}) "
            "must be the same length"
        )
    n = len(x_variant)
    if n < 2:
        raise ValueError("CUPED needs >= 2 paired samples")
    mean_v = sum(x_variant) / n
    mean_b = sum(x_baseline) / n
    cov = sum(
        (v - mean_v) * (b - mean_b) for v, b in zip(x_variant, x_baseline)
    ) / (n - 1)
    var_b = sum((b - mean_b) ** 2 for b in x_baseline) / (n - 1)
    var_v = sum((v - mean_v) ** 2 for v in x_variant) / (n - 1)
    if var_b == 0:
        raise ValueError("baseline has zero variance — CUPED undefined")
    theta = cov / var_b
    rho = (
        cov / math.sqrt(var_v * var_b)
        if var_v > 0 and var_b > 0
        else 0.0
    )
    adjusted = [v - theta * (b - mean_b) for v, b in zip(x_variant, x_baseline)]
    return CupedResult(
        theta=theta,
        rho=rho,
        variance_reduction=rho**2,
        adjusted_values=adjusted,
        n=n,
    )
