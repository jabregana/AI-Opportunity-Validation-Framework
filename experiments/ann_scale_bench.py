"""Compare v0.3.1 (linear cosine scan) vs v0.5.5-ann (HNSW lookup) at
multiple K values on the W-MULTITENANT-SYNTH-replicated workload used by
scale_stress. Reports per-1k-write latency, total ingestion seconds,
final B-cubed F1, and the ratio.

This is the proof for v0.5.5: HNSW restores sub-linear lookup at K~10k+
where v0.3.1 collapses to ~16 writes/sec.

Run:
  .venv/bin/python experiments/ann_scale_bench.py --scale 5000
  .venv/bin/python experiments/ann_scale_bench.py --scale 20000
"""
from __future__ import annotations
import argparse
import gc
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ingest(variant, workload):
    t = time.perf_counter()
    for e in workload:
        variant.align_with_context(e.input, {"source_id": e.source_id})
    return time.perf_counter() - t


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ann-scale-bench")
    parser.add_argument("--scale", type=int, default=5000)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"ann_scale_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    from experiments.scale_stress import synthesize_workload
    from runner.metrics import alignment
    from runner.variants import build

    print(f"Synthesizing workload of {args.scale} entries...")
    workload = synthesize_workload(args.scale)
    print(f"  built {len(workload)} entries, "
          f"{len(set(e.oracle_canonical for e in workload))} oracle canonicals")
    oracle_view = [(e.input, e.oracle_canonical) for e in workload]

    results = []
    for variant_id in ["embed-proxy-v0.3.1", "embed-proxy-v0.5.5-ann"]:
        gc.collect()
        v = build(variant_id)
        print(f"\nVariant {variant_id}")
        if hasattr(v, "ann_backend_name"):
            print(f"  ANN backend: {v.ann_backend_name}")
        secs = _ingest(v, workload)
        rate = len(workload) / secs if secs > 0 else float("inf")
        print(f"  ingestion: {secs:.2f}s, {rate:.0f} writes/sec, "
              f"K_final={v.canonical_count}")

        preds = [(e.input, v.align_with_context(e.input, {"source_id": e.source_id}))
                 for e in workload]
        bc = sum(alignment.per_item_bcubed_f1(preds, oracle_view)) / len(workload)
        print(f"  B-cubed F1: {bc:.4f}")

        results.append({
            "variant": variant_id,
            "ann_backend": getattr(v, "ann_backend_name", None),
            "scale": args.scale,
            "n_entries": len(workload),
            "ingest_seconds": secs,
            "writes_per_second": rate,
            "k_final": v.canonical_count,
            "bcubed_f1": bc,
        })

    if len(results) == 2:
        speedup = results[0]["ingest_seconds"] / results[1]["ingest_seconds"]
        bc_delta = results[1]["bcubed_f1"] - results[0]["bcubed_f1"]
        print(f"\nv0.5.5-ann speedup: {speedup:.2f}x")
        print(f"v0.5.5-ann B-cubed delta vs v0.3.1: {bc_delta:+.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scale": args.scale,
        "results": results,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
