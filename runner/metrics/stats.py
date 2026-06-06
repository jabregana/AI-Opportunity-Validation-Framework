"""Statistical helpers for paired comparisons across variants.

Stdlib-only for the pilot. SciPy will be brought in when we add the full
McNemar exact test, Wilcoxon signed-rank, and Poisson rate-ratio tests
described in experiments.md §5.2.
"""
from __future__ import annotations
import random
from dataclasses import dataclass
from statistics import mean


@dataclass
class BootstrapResult:
    mean_diff: float
    ci_low: float
    ci_high: float
    ci_level: float
    n_resamples: int
    n: int
    p_value_one_sided_gt: float  # P(resampled mean ≤ 0); reject H0: μ ≤ 0 when small
    p_value_two_sided: float


def paired_bootstrap(
    diffs: list[float],
    n_resamples: int = 10_000,
    ci_level: float = 0.95,
    seed: int = 0xC0FFEE,
) -> BootstrapResult:
    """Percentile bootstrap CI + p-values on the mean of paired differences.

    `diffs[i]` is variant_metric[i] - baseline_metric[i] for paired sample i.

    Returns:
      - observed mean diff
      - (1 - alpha) percentile CI
      - one-sided p-value for H0: μ ≤ 0 vs H1: μ > 0
        (fraction of resampled means ≤ 0)
      - two-sided p-value: 2 × min(one-sided, 1 - one-sided)

    BCa will replace percentile when we move past pilot.
    """
    n = len(diffs)
    if n == 0:
        raise ValueError("diffs is empty")
    rng = random.Random(seed)
    resampled_means: list[float] = []
    for _ in range(n_resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        resampled_means.append(mean(sample))
    resampled_means.sort()
    alpha = 1.0 - ci_level
    lo_idx = int((alpha / 2) * n_resamples)
    hi_idx = int((1 - alpha / 2) * n_resamples) - 1
    p_one_sided = sum(1 for m in resampled_means if m <= 0) / n_resamples
    p_two_sided = 2 * min(p_one_sided, 1 - p_one_sided)
    return BootstrapResult(
        mean_diff=mean(diffs),
        ci_low=resampled_means[lo_idx],
        ci_high=resampled_means[hi_idx],
        ci_level=ci_level,
        n_resamples=n_resamples,
        n=n,
        p_value_one_sided_gt=p_one_sided,
        p_value_two_sided=p_two_sided,
    )


def mcnemar_discordant_counts(
    a_correct: list[int], b_correct: list[int]
) -> tuple[int, int]:
    """Count discordant cells for McNemar's test on paired binary outcomes.

    Returns (b, c) where:
      b = count of (a_correct=1, b_correct=0)  -- variant wins
      c = count of (a_correct=0, b_correct=1)  -- baseline wins

    The full exact test will be added with SciPy; for the pilot we just
    surface the counts so the artifact records them.
    """
    if len(a_correct) != len(b_correct):
        raise ValueError("length mismatch")
    b = sum(1 for x, y in zip(a_correct, b_correct) if x == 1 and y == 0)
    c = sum(1 for x, y in zip(a_correct, b_correct) if x == 0 and y == 1)
    return b, c
