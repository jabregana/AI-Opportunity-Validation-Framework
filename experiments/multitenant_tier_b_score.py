"""Score variants against multi-tenant Tier B fixtures.

For each cross-source adversarial pair, ingest both entries through
the variant, run consolidate if applicable, then check whether the
variant emits DIFFERENT canonicals (correct) or merges them (false
merge).

Fresh variant instance per pair to isolate from cross-contamination.

Output: per-variant false-merge rate on each multi-tenant Tier B fixture.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.variants import FACTORIES


def score_fixture(fixture_path: Path, variant_ids: list[str]) -> list[dict]:
    """For each variant, ingest the FULL canonical-source workload first,
    then check each adversarial pair's predicted canonicals on the
    final variant state. This is the realistic test: the variant has
    seen all the data it would see in production, including all aliases
    per (source, local) cluster, so cross-source consolidation has full
    information to make the merge or no-merge decision.
    """
    from fixtures import workloads

    fixture = json.loads(fixture_path.read_text())
    pairs = fixture["pairs"]
    workload_id = fixture["canonical_source"]
    workload = workloads.load(workload_id)
    n = len(pairs)
    results = []
    for variant_id in variant_ids:
        factory = FACTORIES[variant_id]
        v = factory()
        # Ingest the full workload
        for entry in workload:
            v.align_with_context(entry.input, {"source_id": entry.source_id})
        if hasattr(v, "consolidate"):
            v.consolidate()

        false_merges = 0
        merge_examples = []
        for pair in pairs:
            ca = v.align_with_context(pair["input_a"], {"source_id": pair["source_a"]})
            cb = v.align_with_context(pair["input_b"], {"source_id": pair["source_b"]})
            if ca == cb:
                false_merges += 1
                if len(merge_examples) < 5:
                    merge_examples.append({
                        "source_a": pair["source_a"],
                        "input_a": pair["input_a"],
                        "oracle_in_source_a": pair["oracle_in_source_a"],
                        "source_b": pair["source_b"],
                        "input_b": pair["input_b"],
                        "oracle_in_source_b": pair["oracle_in_source_b"],
                        "merged_to": ca,
                    })
        results.append({
            "variant": variant_id,
            "false_merges": false_merges,
            "total_pairs": n,
            "false_merge_rate": false_merges / n if n else 0.0,
            "merge_examples": merge_examples,
        })
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(prog="multitenant-tier-b-score")
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", default=[
        "embed-proxy-v0.4.0-per-source",
        "embed-proxy-v0.4.1-consensus",
        "embed-proxy-v0.4.2-lazy-consensus",
        "embed-proxy-v0.4.3-and-rule",
        "embed-proxy-v0.4.4-adaptive",
    ])
    args = parser.parse_args(argv)

    print(f"Scoring against {args.fixture.name} ({json.loads(args.fixture.read_text())['n_pairs']} pairs)")
    results = score_fixture(args.fixture, args.variants)
    print(f"\n{'variant':40s} {'false_merges':>12s} {'rate':>8s}")
    for r in results:
        print(f"  {r['variant']:38s} {r['false_merges']:>6d}/{r['total_pairs']:<5d} {r['false_merge_rate']:>7.2%}")
        for ex in r["merge_examples"]:
            print(f"      false-merge: ({ex['source_a']}, {ex['input_a']!r}) <-> ({ex['source_b']}, {ex['input_b']!r}) -> {ex['merged_to']!r}")


if __name__ == "__main__":
    main()
