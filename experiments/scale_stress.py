"""Scale stress test for v0.4.x lazy variants.

Synthesizes a large multi-tenant workload (default 100k entries) by
replicating the W-MULTITENANT-SYNTH base with input perturbations and
extra synthetic entities. Measures:

  - Ingestion latency (single-thread total time)
  - Consolidate latency
  - Memory footprint of the variant after ingestion
  - Whether cadence invariance survives at this scale (compare
    consolidate-every-1000 vs consolidate-once)
  - Final B-cubed F1

Run:
  .venv/bin/python experiments/scale_stress.py --scale 100000
"""
from __future__ import annotations
import argparse
import gc
import json
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mem_kb() -> int:
    """Resident set size in kilobytes (best-effort, OS dependent)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def synthesize_workload(target_size: int, base_workload_id: str = "W-MULTITENANT-SYNTH"):
    """Build a workload of approximately target_size entries by replicating
    a base workload with input suffixes and synthesizing additional
    cross-source entities."""
    from fixtures import workloads
    from fixtures.workloads import WorkloadEntry

    base = list(workloads.load(base_workload_id))
    if target_size <= len(base):
        return base[:target_size]
    out = list(base)
    # Replicate with suffix variations to grow the workload while
    # preserving multi-tenant structure
    suffix_pool = [f"_v{i}" for i in range(target_size // len(base) + 1)]
    for s_idx, suffix in enumerate(suffix_pool):
        if len(out) >= target_size:
            break
        for entry in base:
            if len(out) >= target_size:
                break
            new_input = entry.input + suffix
            new_oracle = entry.oracle_canonical + suffix
            out.append(WorkloadEntry(entry.source_id, new_input, new_oracle))
    return out[:target_size]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scale-stress")
    parser.add_argument("--scale", type=int, default=10000,
                        help="target workload size (default 10000; full run uses 100000)")
    parser.add_argument("--variant", default="embed-proxy-v0.4.4-adaptive")
    parser.add_argument("--cadence", type=int, default=0,
                        help="consolidate every N writes; 0 = consolidate once at end")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"scale_stress_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    from runner.variants import build
    from runner.metrics import alignment

    print(f"Synthesizing workload of {args.scale} entries...")
    workload = synthesize_workload(args.scale)
    print(f"  built {len(workload)} entries, "
          f"{len(set(e.source_id for e in workload))} sources, "
          f"{len(set(e.oracle_canonical for e in workload))} oracle canonicals")
    oracle_view = [(e.input, e.oracle_canonical) for e in workload]

    gc.collect()
    mem_before = _mem_kb()
    print(f"\nVariant {args.variant}; cadence {'end-only' if args.cadence == 0 else args.cadence}")

    v = build(args.variant)
    t_ingest = time.perf_counter()
    consolidations = 0
    consolidate_seconds = 0.0
    for i, e in enumerate(workload, 1):
        v.align_with_context(e.input, {"source_id": e.source_id})
        if args.cadence > 0 and i % args.cadence == 0 and hasattr(v, "consolidate"):
            tc = time.perf_counter()
            v.consolidate()
            consolidate_seconds += time.perf_counter() - tc
            consolidations += 1
    ingest_seconds = time.perf_counter() - t_ingest - consolidate_seconds
    print(f"  ingestion: {ingest_seconds:.2f}s ({len(workload)/ingest_seconds:.0f} writes/s)")

    final_consolidate_seconds = 0.0
    if hasattr(v, "consolidate"):
        tc = time.perf_counter()
        consolidation_summary = v.consolidate()
        final_consolidate_seconds = time.perf_counter() - tc
        consolidations += 1
        consolidate_seconds += final_consolidate_seconds
        print(f"  final consolidate: {final_consolidate_seconds:.2f}s, "
              f"{consolidation_summary.get('n_merge_edges', 0)} merges")
    else:
        consolidation_summary = None

    mem_after = _mem_kb()
    mem_delta_mb = (mem_after - mem_before) / 1024.0

    t_query = time.perf_counter()
    preds = [(e.input, v.align_with_context(e.input, {"source_id": e.source_id})) for e in workload]
    query_seconds = time.perf_counter() - t_query
    print(f"  query pass: {query_seconds:.2f}s ({len(workload)/query_seconds:.0f} queries/s)")

    bc_scores = alignment.per_item_bcubed_f1(preds, oracle_view)
    bc_mean = sum(bc_scores) / len(bc_scores)
    print(f"  B-cubed F1: {bc_mean:.4f}")
    print(f"  memory delta: {mem_delta_mb:.0f} MB")

    out_data = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "variant": args.variant,
        "scale": args.scale,
        "cadence": args.cadence,
        "n_entries_actual": len(workload),
        "n_oracle_canonicals": len(set(e.oracle_canonical for e in workload)),
        "n_sources": len(set(e.source_id for e in workload)),
        "ingest_seconds": ingest_seconds,
        "consolidate_seconds": consolidate_seconds,
        "final_consolidate_seconds": final_consolidate_seconds,
        "n_consolidations": consolidations,
        "consolidation_summary": consolidation_summary,
        "query_seconds": query_seconds,
        "ingest_writes_per_second": len(workload) / ingest_seconds if ingest_seconds > 0 else 0,
        "query_queries_per_second": len(workload) / query_seconds if query_seconds > 0 else 0,
        "memory_delta_mb": mem_delta_mb,
        "bcubed_f1": bc_mean,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_data, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
