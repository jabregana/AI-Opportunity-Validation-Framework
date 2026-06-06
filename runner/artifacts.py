"""Run artifact writer per experiments.md §6.1."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
        h.update(b"\x1f")  # unit separator
        h.update(oracle.encode())
        h.update(b"\x1e")  # record separator
    return f"sha256:{h.hexdigest()}"


def emit(
    variant: str,
    baseline: str,
    workload_id: str,
    workload_sha: str,
    use_case: str,
    metrics: dict[str, Any],
    decision: str,
    out_dir: str | os.PathLike[str] = "runs",
) -> Path:
    artifact = {
        "run_id": str(uuid.uuid4()),
        "git_sha": _git_sha(),
        "variant": variant,
        "baseline": baseline,
        "workload_id": workload_id,
        "workload_sha": workload_sha,
        "use_case": use_case,
        "metrics": metrics,
        "decision": decision,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    file_path = out_path / f"run-{artifact['run_id']}.json"
    file_path.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return file_path
