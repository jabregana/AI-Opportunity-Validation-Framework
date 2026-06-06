"""Multi-tenant Tier B adversarial fixture generator.

The existing tier_b_adversarials.py mines pairs of distinct oracle
canonicals that share embedding similarity. That tests false-merge
resistance WITHIN a single canonical-store.

This generator addresses the multi-tenant counterpart: pairs of
(source, surface) entries across DIFFERENT sources that should NOT
merge despite high alias-overlap or embedding similarity. The Apple
case from W-MULTITENANT-WIKIDATA is canonical: tech_company "Apple"
and biology "apple" share the surface "Apple" but mean different
things per oracle.

For each source pair (s1, s2):
  Find entries where:
    s1 and s2 both have an entry with similar input
    The oracle_canonical for s1 differs from the oracle_canonical for s2
  These are cross-source false-merge risks.

The fixture is a list of triples (s1, s2, shared_or_similar_surface,
oracle_in_s1, oracle_in_s2). UC-4.4 cross-source mode verifies that
the variant emits DIFFERENT canonicals for the two entries.

Usage:
  python -m fixtures.generators.multitenant_tier_b \\
    --canonical-source W-MULTITENANT-WIKIDATA \\
    --out fixtures/adversarials/multitenant_tier_b_wikidata.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures import workloads


def _normalize_for_match(text: str) -> str:
    return text.lower().strip()


def mine_cross_source_adversarials(workload, min_input_overlap: int = 1) -> list[dict]:
    """For each pair of sources, find entries where the input is shared or
    very similar but the oracle_canonical differs. These are the cross-
    source pairs that the proxy must keep isolated despite surface
    similarity.

    Returns a list of dicts:
      {"source_a", "source_b", "shared_input",
       "oracle_in_source_a", "oracle_in_source_b"}
    """
    # Index: source -> {normalized_input -> set of (input, oracle)}
    by_source: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for entry in workload:
        norm = _normalize_for_match(entry.input)
        by_source.setdefault(entry.source_id, {}).setdefault(norm, set()).add(
            (entry.input, entry.oracle_canonical)
        )

    pairs: list[dict] = []
    sources = sorted(by_source.keys())
    for i, sa in enumerate(sources):
        for sb in sources[i + 1:]:
            inputs_a = by_source[sa]
            inputs_b = by_source[sb]
            shared = set(inputs_a) & set(inputs_b)
            for norm in sorted(shared):
                for (input_a, oracle_a) in inputs_a[norm]:
                    for (input_b, oracle_b) in inputs_b[norm]:
                        if oracle_a == oracle_b:
                            continue  # same oracle is a TRUE merge case, skip
                        pairs.append({
                            "source_a": sa,
                            "source_b": sb,
                            "input_a": input_a,
                            "input_b": input_b,
                            "shared_normalized": norm,
                            "oracle_in_source_a": oracle_a,
                            "oracle_in_source_b": oracle_b,
                        })
    return pairs


def _fixture_sha256(pairs: list[dict]) -> str:
    h = hashlib.sha256()
    for p in pairs:
        for k in ("source_a", "source_b", "input_a", "input_b",
                  "oracle_in_source_a", "oracle_in_source_b"):
            h.update(p[k].encode())
            h.update(b"\x1f")
        h.update(b"\x1e")
    return f"sha256:{h.hexdigest()}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="multitenant-tier-b")
    parser.add_argument("--canonical-source", required=True,
                        help="workload id from fixtures.workloads.LOADERS")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    w = workloads.load(args.canonical_source)
    pairs = mine_cross_source_adversarials(w)
    sha = _fixture_sha256(pairs)

    fixture = {
        "schema_version": "1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_source": args.canonical_source,
        "n_pairs": len(pairs),
        "pairs": pairs,
        "fixture_sha256": sha,
        "description": (
            "Multi-tenant Tier B adversarials. Each pair is two entries "
            "across different sources that share a surface form but have "
            "different oracle canonicals. A correct multi-tenant variant "
            "must emit different predicted canonicals for the two entries."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2))
    print(f"Wrote {args.out} -- {len(pairs)} cross-source adversarial pairs")
    print(f"  fixture_sha256: {sha}")
    if pairs:
        print(f"  first 5 pairs:")
        for p in pairs[:5]:
            print(
                f"    {p['source_a']}/{p['input_a']!r} -> {p['oracle_in_source_a']!r}  "
                f"vs  {p['source_b']}/{p['input_b']!r} -> {p['oracle_in_source_b']!r}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
