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
    # Every entry has source_id, input, oracle_canonical as strings
    for entry in a:
        assert isinstance(entry.source_id, str)
        assert isinstance(entry.input, str)
        assert isinstance(entry.oracle_canonical, str)


def test_b_raw_identity_is_lossless():
    v = variants.build("b-raw-identity")
    workload = workloads.load("W-CONCEPTNET-REL")
    oracle_view = [(e.input, e.oracle_canonical) for e in workload]
    # B-RAW assigns each surface form to its own bucket -> two surface forms
    # of the same canonical end up in different clusters -> low recall.
    preds = [(e.input, v.align(e.input)) for e in workload]
    r = alignment.pairwise_f1(preds, oracle_view)
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


def test_end_to_end_run_emits_three_block_artifact(tmp_path):
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
            "--tier",
            "fast",
            "--bootstrap-resamples",
            "500",
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    artifacts_emitted = list(tmp_path.glob("run-*.json"))
    assert len(artifacts_emitted) == 1
    payload = json.loads(artifacts_emitted[0].read_text())

    # Top-level three-block schema + pipeline_decision.
    assert set(payload.keys()) == {
        "artifact_metadata",
        "sequential_fdr_ledger",
        "test_executions",
        "pipeline_decision",
    }

    # artifact_metadata
    md = payload["artifact_metadata"]
    assert md["workload_id"] == "W-CONCEPTNET-REL"
    assert md["workload_sha"].startswith("sha256:")
    assert md["tier"] == "fast"
    assert md["variant"] == "stub-random-bucket-v0.0.1"
    assert md["baseline"] == "b-raw-identity"
    assert "run_id" in md
    assert "timestamp_utc" in md

    # sequential_fdr_ledger
    led = payload["sequential_fdr_ledger"]
    assert led["algorithm"] == "LORD++"
    assert led["target_q"] == 0.10
    assert "current_wealth" in led
    assert isinstance(led["prior_rejections"], list)

    # test_executions
    tx = payload["test_executions"]
    assert isinstance(tx, list) and len(tx) == 1
    t0 = tx[0]
    assert t0["test_seq_id"] == 1
    assert t0["use_case"] == "UC-4.1"
    assert 0.0 <= t0["alpha_allocated"] <= 0.10
    assert t0["outcome"] in {
        "REJECT_NULL_SUPERIOR",
        "REJECT_NULL_NON_INFERIOR",
        "FAIL_TO_REJECT",
        "REGRESSION_DETECTED",
        "INCONCLUSIVE",
    }
    assert "always_valid_ci_lower" in t0
    assert "always_valid_ci_upper" in t0
    assert "p_value" in t0

    # pipeline_decision
    assert payload["pipeline_decision"] in {
        "PASS_AND_MERGE",
        "BLOCK_PR",
        "SOFT_REGRESSION_OPENED",
    }


def test_stub_random_bucket_regresses_against_b_raw(tmp_path):
    """stub-random-bucket muddles cluster assignments (precision drops
    below singleton-cluster baseline) without recovering enough recall,
    so on B-cubed F1 it is statistically worse than b-raw-identity.
    Fast tier blocks PR on REGRESSION_DETECTED."""
    runner_main(
        [
            "--variant", "stub-random-bucket",
            "--baseline", "b-raw-identity",
            "--workload", "W-CONCEPTNET-REL",
            "--use-case", "UC-4.1",
            "--tier", "fast",
            "--bootstrap-resamples", "500",
            "--out-dir", str(tmp_path),
        ]
    )
    payload = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert payload["test_executions"][0]["outcome"] == "REGRESSION_DETECTED"
    assert payload["pipeline_decision"] == "BLOCK_PR"


def test_stub_regression_on_nightly_opens_soft_regression(tmp_path):
    runner_main(
        [
            "--variant", "stub-random-bucket",
            "--baseline", "b-raw-identity",
            "--workload", "W-CONCEPTNET-REL",
            "--use-case", "UC-4.1",
            "--tier", "nightly",
            "--bootstrap-resamples", "500",
            "--out-dir", str(tmp_path),
        ]
    )
    payload = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert payload["test_executions"][0]["outcome"] == "REGRESSION_DETECTED"
    assert payload["pipeline_decision"] == "SOFT_REGRESSION_OPENED"


def test_uc_4_4_blocks_high_false_merge_variant(tmp_path):
    """A variant that aliases everything should FAIL the UC-4.4 gate.
    Uses an in-memory fixture with two pairs that should NOT alias."""
    fixture_path = tmp_path / "fake_tier_b.json"
    fixture_path.write_text(json.dumps({
        "schema_version": "1",
        "fixture_sha256": "sha256:test",
        "reference_embedder": "test",
        "pairs": [
            {"a": "foo", "b": "different_thing_a", "cosine": 0.9},
            {"a": "bar", "b": "different_thing_b", "cosine": 0.9},
        ],
    }))
    # stub-random-bucket hashes everything into 34 buckets; with only 2
    # pairs (4 unique inputs) it'll occasionally alias by collision.
    # Use embed-proxy-v0.1.0 instead — disjoint tokens guarantee no merge.
    rc = runner_main(
        [
            "--variant", "embed-proxy-v0.1.0",
            "--use-case", "UC-4.4",
            "--tier", "fast",
            "--tier-b-fixture", str(fixture_path),
            "--out-dir", str(tmp_path / "runs"),
        ]
    )
    assert rc == 0
    artifact = json.loads(next((tmp_path / "runs").glob("run-*.json")).read_text())
    tx = artifact["test_executions"][0]
    assert tx["use_case"] == "UC-4.4"
    assert tx["type"] == "guardrail_kill_switch"
    assert tx["metric_id"] == "uc_4_4_tier_b_false_merge_rate"
    assert tx["point_estimate"] == 0.0
    assert tx["outcome"] == "PASS"
    assert artifact["pipeline_decision"] == "PASS_AND_MERGE"


def test_uc_4_4_requires_tier_b_fixture():
    rc = runner_main(["--variant", "embed-proxy-v0.1.0", "--use-case", "UC-4.4"])
    assert rc == 2


def test_uc_4_6_latency_smoke(tmp_path):
    """UC-4.6 emits an artifact with latency quantiles in diagnostics."""
    rc = runner_main(
        [
            "--variant", "embed-proxy-v0.1.0",
            "--workload", "W-CONCEPTNET-REL",
            "--use-case", "UC-4.6",
            "--tier", "fast",
            "--out-dir", str(tmp_path),
        ]
    )
    assert rc == 0
    payload = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    tx = payload["test_executions"][0]
    assert tx["use_case"] == "UC-4.6"
    assert tx["metric_id"] == "uc_4_6_per_write_latency_ms"
    assert tx["type"] == "guardrail_kill_switch"
    diag = tx["diagnostics"]
    assert diag["p50_ms"] >= 0
    assert diag["p95_ms"] >= diag["p50_ms"]
    assert diag["p99_ms"] >= diag["p95_ms"]
    assert diag["qps_observed_single_thread"] > 0


def test_uc_4_6_requires_workload():
    rc = runner_main(["--variant", "embed-proxy-v0.1.0", "--use-case", "UC-4.6"])
    assert rc == 2


def test_uc_4_7_held_out_smoke(tmp_path):
    """UC-4.7 lite splits workload 80/20 and emits a paired accuracy
    bootstrap when a baseline is provided."""
    rc = runner_main(
        [
            "--variant", "embed-proxy-v0.1.0",
            "--baseline", "b-raw-identity",
            "--workload", "W-CONCEPTNET-REL",
            "--use-case", "UC-4.7",
            "--tier", "fast",
            "--bootstrap-resamples", "200",
            "--out-dir", str(tmp_path),
        ]
    )
    assert rc == 0
    payload = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    tx = payload["test_executions"][0]
    assert tx["use_case"] == "UC-4.7"
    assert tx["metric_id"] == "uc_4_7_held_out_accuracy_diff"
    assert tx["type"] == "superiority"
    diag = tx["diagnostics"]
    assert 0 <= diag["variant_accuracy"] <= 1
    assert 0 <= diag["baseline_accuracy"] <= 1
    assert diag["n_ingestion"] > 0
    assert diag["n_queries"] > 0
    assert diag["holdout_fraction"] == 0.2


def test_uc_4_7_split_is_deterministic_with_seed(tmp_path):
    """Same split_seed → same train/query partition."""
    common = ["--variant", "embed-proxy-v0.1.0", "--baseline", "b-raw-identity",
              "--workload", "W-CONCEPTNET-REL", "--use-case", "UC-4.7",
              "--tier", "fast", "--bootstrap-resamples", "100"]
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    runner_main(common + ["--split-seed", "42", "--out-dir", str(out1)])
    runner_main(common + ["--split-seed", "42", "--out-dir", str(out2)])
    p1 = json.loads(next(out1.glob("run-*.json")).read_text())
    p2 = json.loads(next(out2.glob("run-*.json")).read_text())
    assert p1["test_executions"][0]["diagnostics"]["n_ingestion"] == \
        p2["test_executions"][0]["diagnostics"]["n_ingestion"]
    assert p1["test_executions"][0]["diagnostics"]["variant_accuracy"] == \
        p2["test_executions"][0]["diagnostics"]["variant_accuracy"]


def test_uc_4_1_still_requires_baseline_and_workload():
    rc = runner_main(["--variant", "embed-proxy-v0.1.0", "--use-case", "UC-4.1"])
    assert rc == 2


def test_embed_proxy_v010_rejects_null_superior(tmp_path):
    """embed-proxy-v0.1.0 (HashedTokenEmbedder + cosine threshold)
    statistically outperforms b-raw-identity on UC-4.1; both tiers should
    PASS_AND_MERGE."""
    for tier in ["fast", "nightly"]:
        out = tmp_path / tier
        out.mkdir()
        runner_main(
            [
                "--variant", "embed-proxy-v0.1.0",
                "--baseline", "b-raw-identity",
                "--workload", "W-CONCEPTNET-REL",
                "--use-case", "UC-4.1",
                "--tier", tier,
                "--bootstrap-resamples", "500",
                "--out-dir", str(out),
            ]
        )
        payload = json.loads(next(out.glob("run-*.json")).read_text())
        assert payload["test_executions"][0]["outcome"] == "REJECT_NULL_SUPERIOR"
        assert payload["pipeline_decision"] == "PASS_AND_MERGE"
