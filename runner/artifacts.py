"""Run artifact writer per experiments.md §6.1.

Three-block schema:

    {
      "artifact_metadata":   { run_id, git_sha, variant, baseline, ... },
      "sequential_fdr_ledger": { algorithm, target_q, wealth, ... },
      "test_executions":      [ { test_seq_id, use_case, metric_id, ... } ],
      "pipeline_decision":    "PASS_AND_MERGE | BLOCK_PR | ..."
    }

Artifacts are immutable. Diffs across runs are computed post-hoc.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.fdr import LordPlusPlusLedger, _GAMMA_CONSTANT


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def workload_sha256(items: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for inp, oracle in items:
        h.update(inp.encode())
        h.update(b"\x1f")
        h.update(oracle.encode())
        h.update(b"\x1e")
    return f"sha256:{h.hexdigest()}"


def _ledger_block(ledger: LordPlusPlusLedger, scope: str = "per_release") -> dict:
    """Serialize the LORD++ ledger state for the sequential_fdr_ledger block."""
    return {
        "algorithm": "LORD++",
        "ledger_scope": scope,
        "target_q": ledger.target_q,
        "gamma_schedule": f"{ledger.gamma_constant} / (n * log2(n+1)^2)",
        "gamma_constant": ledger.gamma_constant,
        "initial_wealth": ledger.W_0,
        "current_wealth": ledger.current_wealth,
        "prior_rejections": ledger.rejections,
    }


def emit(
    *,
    variant_name: str,
    baseline_name: str,
    workload_id: str,
    workload_sha: str,
    tier: str,
    test_executions: list[dict],
    ledger: LordPlusPlusLedger,
    pipeline_decision: str,
    ledger_scope: str = "per_release",
    out_dir: str | os.PathLike[str] = "runs",
) -> Path:
    """Write one run artifact in the three-block schema."""
    if tier not in {"fast", "nightly"}:
        raise ValueError(f"tier must be 'fast' or 'nightly', got {tier!r}")
    artifact = {
        "artifact_metadata": {
            "run_id": str(uuid.uuid4()),
            "git_sha": _git_sha(),
            "variant": variant_name,
            "baseline": baseline_name,
            "workload_id": workload_id,
            "workload_sha": workload_sha,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "tier": tier,
        },
        "sequential_fdr_ledger": _ledger_block(ledger, scope=ledger_scope),
        "test_executions": test_executions,
        "pipeline_decision": pipeline_decision,
    }
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = (
        out_path / f"run-{artifact['artifact_metadata']['run_id']}.json"
    )
    file_path.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return file_path
