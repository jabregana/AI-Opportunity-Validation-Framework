from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math
import random

import pytest

from runner.cuped import cuped_adjust


def test_identity_baseline_full_reduction():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    r = cuped_adjust(x_variant=xs, x_baseline=xs)
    assert r.rho == pytest.approx(1.0)
    assert r.variance_reduction == pytest.approx(1.0)
    # Adjusted values collapse to the mean — variance is zero.
    mean = sum(xs) / len(xs)
    assert all(abs(v - mean) < 1e-9 for v in r.adjusted_values)


def test_zero_correlation_no_reduction():
    rng = random.Random(0)
    n = 1000
    baseline = [rng.gauss(0, 1) for _ in range(n)]
    variant = [rng.gauss(0, 1) for _ in range(n)]  # independent
    r = cuped_adjust(variant, baseline)
    assert abs(r.rho) < 0.1
    assert r.variance_reduction < 0.05


def test_variance_reduction_matches_rho_squared():
    # Construct a controlled case: variant = α · baseline + ε, where
    # baseline ~ N(0, 1), ε ~ N(0, σ_ε²). Then ρ² = α² / (α² + σ_ε²).
    rng = random.Random(42)
    n = 5000
    alpha = 1.0
    sigma_eps = 1.0
    baseline = [rng.gauss(0, 1) for _ in range(n)]
    eps = [rng.gauss(0, sigma_eps) for _ in range(n)]
    variant = [alpha * b + e for b, e in zip(baseline, eps)]
    r = cuped_adjust(variant, baseline)
    expected_rho_sq = alpha**2 / (alpha**2 + sigma_eps**2)
    assert r.rho**2 == pytest.approx(expected_rho_sq, abs=0.05)
    # variance_reduction is the fraction of σ² removed = ρ²
    assert r.variance_reduction == pytest.approx(expected_rho_sq, abs=0.05)


def test_adjusted_variance_actually_lower():
    rng = random.Random(7)
    n = 2000
    baseline = [rng.gauss(0, 1) for _ in range(n)]
    variant = [0.7 * b + rng.gauss(0, 0.5) for b in baseline]
    r = cuped_adjust(variant, baseline)
    mean_v = sum(variant) / n
    var_v = sum((v - mean_v) ** 2 for v in variant) / (n - 1)
    mean_a = sum(r.adjusted_values) / n
    var_a = sum((v - mean_a) ** 2 for v in r.adjusted_values) / (n - 1)
    # Remaining-variance fraction = (1 − reduction fraction)
    assert var_a < var_v
    assert var_a / var_v == pytest.approx(1 - r.variance_reduction, abs=0.05)


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        cuped_adjust([1.0, 2.0], [1.0])


def test_zero_baseline_variance_raises():
    with pytest.raises(ValueError):
        cuped_adjust([1.0, 2.0, 3.0], [5.0, 5.0, 5.0])
