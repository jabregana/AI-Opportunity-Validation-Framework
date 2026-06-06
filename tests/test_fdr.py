from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math

import pytest

from runner.fdr import LordPlusPlusLedger, gamma, run_ledger


def test_gamma_is_strictly_decreasing():
    vals = [gamma(n) for n in range(1, 50)]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_gamma_partial_sum_bounded():
    # The FDR-control invariant is Σ γ_n ≤ 1 (Ramdas et al. 2017).
    # With c = 0.4412 over the (n · log₂²(n+1)) form, the 10k-term partial
    # sum is ~0.70 and the tail adds slowly — well within the bound. Σ ≤ 1
    # is what matters; tighter normalization is a power optimization, not
    # a correctness requirement.
    s = sum(gamma(n) for n in range(1, 10_000))
    assert 0.5 < s <= 1.0


def test_wealth_stays_non_negative_under_no_rejection():
    # If no test rejects, wealth strictly decreases; with Σ γ_n ≤ 1 and
    # initial wealth W_0 < q, wealth approaches 0 from above but must
    # never cross zero. Non-negativity is the operational invariant for
    # FDR control.
    led = LordPlusPlusLedger(target_q=0.10, initial_wealth_ratio=0.5)
    for n in range(1, 1000):
        led.record(n, p_value=0.99)
    assert all(w >= -1e-12 for w in led.wealth_history)


def test_initial_wealth():
    led = LordPlusPlusLedger(target_q=0.10, initial_wealth_ratio=0.5)
    assert led.current_wealth == pytest.approx(0.05)
    assert led.W_0 == pytest.approx(0.05)


def test_alpha_decreases_with_no_rejections():
    led = LordPlusPlusLedger(target_q=0.10)
    alphas = [led.alpha_at(n) for n in range(1, 20)]
    assert all(alphas[i] > alphas[i + 1] for i in range(len(alphas) - 1))


def test_rejection_boosts_future_alpha():
    led_a = LordPlusPlusLedger(target_q=0.10)
    led_b = LordPlusPlusLedger(target_q=0.10)
    # led_a: never rejects; led_b: rejects at step 1.
    for n in range(1, 6):
        led_a.record(n, p_value=0.99)  # never reject
    led_b.record(1, p_value=0.0)  # forced reject
    for n in range(2, 6):
        led_b.record(n, p_value=0.99)
    assert led_b.alpha_at(6) > led_a.alpha_at(6)


def test_record_returns_decision_and_mutates_state():
    led = LordPlusPlusLedger(target_q=0.10)
    alpha_1, rejected_1 = led.record(1, p_value=0.0)
    assert rejected_1 is True
    assert led.rejections == [1]
    alpha_2, rejected_2 = led.record(2, p_value=0.99)
    assert rejected_2 is False
    assert alpha_2 < alpha_1 + 0.10  # bounded sanity


def test_record_enforces_order():
    led = LordPlusPlusLedger()
    led.record(1, 0.5)
    with pytest.raises(ValueError):
        led.record(3, 0.5)  # skipped 2


def test_run_ledger_attaches_alpha_and_outcome():
    tests = [
        {"test_seq_id": 1, "p_value": 0.001, "metric_id": "kill_switch_a"},
        {"test_seq_id": 2, "p_value": 0.5, "metric_id": "non_inferiority_b"},
        {"test_seq_id": 3, "p_value": 0.01, "metric_id": "primary_c"},
    ]
    ordered, led = run_ledger(tests, target_q=0.10)
    for t in ordered:
        assert "alpha_allocated" in t
        assert "outcome_rejected" in t
        assert 0.0 <= t["alpha_allocated"] <= 0.10
    # Test 1 has tiny p — must reject; test 2 has large p — cannot reject.
    assert ordered[0]["outcome_rejected"] is True
    assert ordered[1]["outcome_rejected"] is False
    # Wealth never crashes below zero with these inputs.
    assert all(w >= -1e-9 for w in led.wealth_history)


def test_alpha_is_pure():
    led = LordPlusPlusLedger()
    a1 = led.alpha_at(5)
    a2 = led.alpha_at(5)
    assert a1 == a2
    assert led.current_wealth == led.W_0  # alpha_at did not mutate
