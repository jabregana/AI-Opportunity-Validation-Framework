from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.gates import (
    MAX_BVPREV_AGE_DAYS,
    SAFFRON_PI0_THRESHOLD,
    bvprev_age_ok,
    inconclusive_is_fail,
    saffron_hot_swap_recommendation,
)


def test_inconclusive_fast_tier_fails():
    r = inconclusive_is_fail(
        ["PASS", "INCONCLUSIVE", "REJECT_NULL_NON_INFERIOR"], tier="fast"
    )
    assert r.passed is False
    assert "INCONCLUSIVE" in r.reason


def test_inconclusive_nightly_passes_through():
    r = inconclusive_is_fail(["PASS", "INCONCLUSIVE"], tier="nightly")
    assert r.passed is True


def test_no_inconclusive_passes():
    r = inconclusive_is_fail(["PASS", "REJECT_NULL_NON_INFERIOR"], tier="fast")
    assert r.passed is True


def test_saffron_swap_above_threshold():
    pi0 = [0.8] * 30
    r = saffron_hot_swap_recommendation(pi0)
    assert r.passed is False
    assert "SAFFRON" in r.reason


def test_saffron_swap_below_threshold():
    pi0 = [0.5] * 30
    r = saffron_hot_swap_recommendation(pi0)
    assert r.passed is True


def test_saffron_swap_empty_history():
    r = saffron_hot_swap_recommendation([])
    assert r.passed is True
    assert "no 30d history" in r.reason


def test_bvprev_age_fresh(tmp_path):
    artifact = tmp_path / "bvprev.json"
    now = datetime.now(timezone.utc)
    artifact.write_text(
        json.dumps(
            {
                "artifact_metadata": {
                    "timestamp_utc": (now - timedelta(days=3)).isoformat()
                }
            }
        )
    )
    r = bvprev_age_ok(artifact, now=now)
    assert r.passed is True
    assert "3d" in r.reason


def test_bvprev_age_stale(tmp_path):
    artifact = tmp_path / "bvprev.json"
    now = datetime.now(timezone.utc)
    artifact.write_text(
        json.dumps(
            {
                "artifact_metadata": {
                    "timestamp_utc": (now - timedelta(days=30)).isoformat()
                }
            }
        )
    )
    r = bvprev_age_ok(artifact, now=now)
    assert r.passed is False
    assert "30d" in r.reason
    assert str(MAX_BVPREV_AGE_DAYS) in r.reason


def test_bvprev_legacy_schema_supported(tmp_path):
    artifact = tmp_path / "bvprev.json"
    now = datetime.now(timezone.utc)
    artifact.write_text(
        json.dumps(
            {"timestamp_utc": (now - timedelta(days=5)).isoformat()}
        )
    )
    r = bvprev_age_ok(artifact, now=now)
    assert r.passed is True


def test_bvprev_missing_file(tmp_path):
    r = bvprev_age_ok(tmp_path / "does-not-exist.json")
    assert r.passed is False
    assert "not found" in r.reason


def test_bvprev_missing_timestamp(tmp_path):
    artifact = tmp_path / "bvprev.json"
    artifact.write_text(json.dumps({"artifact_metadata": {}}))
    r = bvprev_age_ok(artifact)
    assert r.passed is False
    assert "timestamp" in r.reason
