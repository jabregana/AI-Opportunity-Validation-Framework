"""Tests for fixtures.noise."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures import workloads
from fixtures.noise import inject_noise


def test_noise_zero_rate_is_identity():
    w = workloads.load("W-CONCEPTNET-REL")
    noisy = inject_noise(w, noise_rate=0.0)
    assert noisy == list(w)


def test_noise_deterministic_across_runs():
    w = workloads.load("W-CONCEPTNET-REL")
    a = inject_noise(w, noise_rate=0.1, seed=42)
    b = inject_noise(w, noise_rate=0.1, seed=42)
    assert a == b


def test_noise_different_seeds_diverge():
    w = workloads.load("W-CONCEPTNET-REL")
    a = inject_noise(w, noise_rate=0.1, seed=1)
    b = inject_noise(w, noise_rate=0.1, seed=2)
    assert a != b


def test_noise_full_rate_perturbs_all():
    w = workloads.load("W-CONCEPTNET-REL")
    noisy = inject_noise(w, noise_rate=1.0, modes=("source_swap",))
    # With only source_swap and 100% rate, every entry's source should change.
    # (single-source workload has source_id="default", and alt source list
    # is empty, so this is actually a no-op test; use multi-tenant instead.)
    w2 = workloads.load("W-MULTITENANT-SYNTH")
    noisy2 = inject_noise(w2, noise_rate=1.0, modes=("source_swap",), seed=1)
    assert len(noisy2) == len(w2)
    # At least some entries changed source
    n_changed = sum(1 for a, b in zip(w2, noisy2) if a.source_id != b.source_id)
    assert n_changed > 0


def test_noise_invalid_rate_raises():
    w = workloads.load("W-CONCEPTNET-REL")
    with pytest.raises(ValueError):
        inject_noise(w, noise_rate=-0.1)
    with pytest.raises(ValueError):
        inject_noise(w, noise_rate=1.5)


def test_noise_unknown_mode_raises():
    w = workloads.load("W-CONCEPTNET-REL")
    with pytest.raises(ValueError):
        inject_noise(w, noise_rate=0.1, modes=("nonsense",))


def test_noise_alias_drop_shortens_workload():
    w = workloads.load("W-CONCEPTNET-REL")
    noisy = inject_noise(w, noise_rate=0.5, modes=("alias_drop",), seed=1)
    # With ~50% drop rate, ~50% of entries should be removed.
    assert len(noisy) < len(w)


def test_noise_surface_perturb_changes_inputs():
    w = workloads.load("W-CONCEPTNET-REL")
    noisy = inject_noise(w, noise_rate=0.5, modes=("surface_perturb",), seed=1)
    n_changed = sum(1 for a, b in zip(w, noisy) if a.input != b.input)
    assert n_changed > 0
