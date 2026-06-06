"""Compare v0.5.3 (multi-tenant, linear-scan inners) vs v0.5.7 (same
algorithm with ANN-backed inners) at multi-tenant scale. This is the
multi-tenant counterpart to experiments/ann_scale_bench.py.

The proxy's hot path on the multi-tenant variants is dominated by the
per-source inner variant's cosine scan. With many sources × many
canonicals per source, that scan dominates. v0.5.7 swaps the inner
for the v0.5.5 ANN-backed proxy. This script measures the ingestion
speedup and confirms no quality loss vs v0.5.3.

Run:
  .venv/bin/python experiments/mt_ann_scale_bench.py --scale 5000
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


def _run(variant_id: str, workload):
    from runner.metrics import alignment
    from runner.variants import build

    gc.collect()
    v = build(variant_id)
    t = time.perf_counter()
    for e in workload:
        v.align_with_context(e.input, {"source_id": e.source_id})
    ingest_s = time.perf_counter() - t

    t = time.perf_counter()
    if hasattr(v, "consolidate"):
        consolidate_summary = v.consolidate()
    else:
        consolidate_summary = None
    consolidate_s = time.perf_counter() - t

    preds = [(e.input, v.align_with_context(e.input, {"source_id": e.source_id}))
             for e in workload]
    oracle = [(e.input, e.oracle_canonical) for e in workload]
    bc = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)

    k_per_source = sum(
        getattr(inner, "canonical_count", 0)
        for inner in getattr(v, "_per_source", {}).values()
    )
    n_sources = len(getattr(v, "_per_source", {}))

    return {
        "variant": variant_id,
        "n_entries": len(workload),
        "n_sources": n_sources,
        "k_total_canonicals": k_per_source,
        "ingest_seconds": ingest_s,
        "writes_per_second": len(workload) / ingest_s if ingest_s > 0 else float("inf"),
        "consolidate_seconds": consolidate_s,
        "bcubed_f1": bc,
        "consolidate_summary": consolidate_summary,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mt-ann-scale-bench")
    parser.add_argument("--scale", type=int, default=3000)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"mt_ann_scale_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    from experiments.scale_stress import synthesize_workload

    print(f"Synthesizing multi-tenant workload of {args.scale} entries...")
    workload = synthesize_workload(args.scale)
    n_sources = len(set(e.source_id for e in workload))
    print(f"  built {len(workload)} entries across {n_sources} sources, "
          f"{len(set(e.oracle_canonical for e in workload))} oracle canonicals")

    results = []
    for variant_id in [
        "embed-proxy-v0.5.3-singleton-aware",
        "embed-proxy-v0.5.7-mt-ann",
    ]:
        print(f"\nRunning {variant_id}...")
        r = _run(variant_id, workload)
        print(f"  ingest: {r['ingest_seconds']:.2f}s "
              f"({r['writes_per_second']:.0f} writes/sec)")
        print(f"  consolidate: {r['consolidate_seconds']:.2f}s")
        print(f"  per-source K total: {r['k_total_canonicals']} "
              f"across {r['n_sources']} sources")
        print(f"  B-cubed F1: {r['bcubed_f1']:.4f}")
        results.append(r)

    if len(results) == 2:
        ref, ann = results
        speedup = ref["ingest_seconds"] / ann["ingest_seconds"]
        bc_delta = ann["bcubed_f1"] - ref["bcubed_f1"]
        print(f"\nv0.5.7 (mt-ann) ingest speedup: {speedup:.2f}x")
        print(f"v0.5.7 B-cubed delta vs v0.5.3: {bc_delta:+.4f}")

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
