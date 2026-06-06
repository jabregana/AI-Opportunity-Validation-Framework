"""Smoke tests for the harness — quick to run, fail loudly if anything breaks."""
from __future__ import annotations
import json
import sys
from pathlib import Path

# Make repo root importable when running `pytest` from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures import workloads
from runner import variants
from runner.metrics import alignment, stats
from runner.runner import main as runner_main


def test_workload_loads_and_is_deterministic():
    a = workloads.load("W-CONCEPTNET-REL")
    b = workloads.load("W-CONCEPTNET-REL")
    assert a == b
    assert len(a) > 100  # enough items for the pilot
    # Every item is (str, str)
    assert all(isinstance(x, str) and isinstance(y, str) for x, y in a)


def test_b_raw_identity_is_lossless():
    v = variants.build("b-raw-identity")
    workload = workloads.load("W-CONCEPTNET-REL")
    # B-RAW assigns each surface form to its own bucket -> two surface forms
    # of the same canonical end up in different clusters -> low recall.
    preds = [(inp, v.align(inp)) for inp, _ in workload]
    r = alignment.pairwise_f1(preds, workload)
    assert r.precision == 0.0 or r.tp == 0  # no merges happened
    assert r.recall == 0.0  # therefore recall is zero


def test_stub_proxy_is_deterministic():
    v1 = variants.build("stub-random-bucket")
    v2 = variants.build("stub-random-bucket")
    assert v1.align("IsA") == v2.align("IsA")


def test_paired_bootstrap_ci_brackets_mean():
    # Constant diff -> CI should be near-zero-width around the constant.
    bs = stats.paired_bootstrap([0.5] * 50, n_resamples=2000)
    assert bs.mean_diff == 0.5
    assert abs(bs.ci_low - 0.5) < 1e-9
    assert abs(bs.ci_high - 0.5) < 1e-9


def test_paired_bootstrap_handles_variance():
    # Mixed diffs -> CI should bracket the mean.
    diffs = [1.0, -1.0, 1.0, -1.0, 0.5, -0.5] * 10
    bs = stats.paired_bootstrap(diffs, n_resamples=3000)
    assert bs.ci_low <= bs.mean_diff <= bs.ci_high


def test_end_to_end_run_emits_artifact(tmp_path):
    rc = runner_main(
        [
            "--variant",
            "stub-random-bucket",
            "--baseline",
            "b-raw-identity",
            "--workload",
            "W-CONCEPTNET-REL",
            "--use-case",
            "UC-4.1",
            "--bootstrap-resamples",
            "500",  # speed up the test
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    artifacts_emitted = list(tmp_path.glob("run-*.json"))
    assert len(artifacts_emitted) == 1
    payload = json.loads(artifacts_emitted[0].read_text())
    assert payload["use_case"] == "UC-4.1"
    assert payload["workload_id"] == "W-CONCEPTNET-REL"
    assert payload["workload_sha"].startswith("sha256:")
    assert payload["decision"] in {"pass", "regress", "inconclusive"}
    assert "uc_4_1" in payload["metrics"]
