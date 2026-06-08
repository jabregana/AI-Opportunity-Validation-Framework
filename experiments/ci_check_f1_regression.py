"""CI guard: read an F1 benchmark artifact; fail non-zero if any variant
regresses below the configured F1-preservation floor.

Usage:
  python experiments/ci_check_f1_regression.py path/to/artifact.json \
      --min-f1-preservation 75.0

The artifact must be the shape produced by gc_retrieval_f1_benchmark.py:
  {
    "per_variant": {
      "<variant_id>": {
        "f1_preservation_pct": float,
        "store_reduction_pct": float,
        ...
      },
      ...
    }
  }

A variant passes if f1_preservation_pct >= --min-f1-preservation OR
store_reduction_pct == 0 (a no-op sweep is not a regression — nothing
was removed). Anything else fails CI.

Exit codes:
  0 - all variants pass
  1 - one or more variants regressed
  2 - artifact missing or malformed
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(prog="ci-check-f1-regression")
    p.add_argument("artifact", type=Path)
    p.add_argument("--min-f1-preservation", type=float, default=75.0,
                   help="Floor (percent) below which a variant fails CI")
    args = p.parse_args()

    if not args.artifact.is_file():
        print(f"ERROR: artifact not found: {args.artifact}", file=sys.stderr)
        return 2

    try:
        data = json.loads(args.artifact.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: malformed JSON in {args.artifact}: {e}", file=sys.stderr)
        return 2

    per_variant = data.get("per_variant") or {}
    if not per_variant:
        print(f"ERROR: 'per_variant' missing or empty in {args.artifact}",
              file=sys.stderr)
        return 2

    print(f"F1 regression check (floor: {args.min_f1_preservation}%)")
    print(f"Artifact: {args.artifact}")
    print()

    failures = []
    for vid, vd in per_variant.items():
        f1_pres = float(vd.get("f1_preservation_pct", 0.0))
        reduction = float(vd.get("store_reduction_pct", 0.0))
        status = "PASS"
        if reduction == 0:
            status = "PASS (no-op sweep)"
        elif f1_pres < args.min_f1_preservation:
            status = "FAIL"
            failures.append((vid, f1_pres, reduction))
        print(f"  [{status:18s}] {vid}: "
              f"{reduction:.1f}% reduction at {f1_pres:.1f}% F1 preservation")

    print()
    if failures:
        print(f"FAIL: {len(failures)} variant(s) below {args.min_f1_preservation}%")
        for vid, f1, red in failures:
            print(f"  - {vid}: {f1:.1f}% < {args.min_f1_preservation}% "
                  f"(at {red:.1f}% reduction)")
        return 1
    print("PASS: all variants meet floor")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
