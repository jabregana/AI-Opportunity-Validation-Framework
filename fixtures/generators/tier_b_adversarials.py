"""UC-4.4 Tier B adversarial pair generator.

For each oracle canonical, embed it with a reference (typically neural)
embedder. Keep pairs (a, b) where:
  - a and b have different oracle canonicals
  - cosine(embed(a), embed(b)) >= cosine_threshold

These are "embedding-near-duplicates that the oracle says are distinct"
- the worst-case test the schema-alignment proxy must resist. A proxy
that aliases these pairs is exhibiting semantic over-clustering.

The output is a JSON fixture committed under fixtures/adversarials/,
SHA-pinned per generation run so UC-4.4 runs can replay against an
immutable adversarial set.

Usage:
  python -m fixtures.generators.tier_b_adversarials \\
    --canonical-source W-CONCEPTNET-REL \\
    --reference-embedder model2vec \\
    --cosine-threshold 0.85 \\
    --out fixtures/adversarials/conceptnet_tier_b.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Importable as a module: from fixtures.generators.tier_b_adversarials import mine
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fixtures import workloads


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def mine(
    canonical_set: list[str],
    embedder,
    cosine_threshold: float = 0.85,
) -> list[dict]:
    """Return adversarial pairs sorted by descending cosine.

    Each pair: {"a": str, "b": str, "cosine": float}. a < b lexically
    so the output is deterministic across runs.
    """
    n = len(canonical_set)
    embeds = [embedder.embed(c) for c in canonical_set]
    pairs: list[dict] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine(embeds[i], embeds[j])
            if sim >= cosine_threshold:
                a, b = sorted([canonical_set[i], canonical_set[j]])
                pairs.append({"a": a, "b": b, "cosine": sim})
    pairs.sort(key=lambda p: (-p["cosine"], p["a"], p["b"]))
    return pairs


def _fixture_sha256(pairs: list[dict]) -> str:
    """SHA-256 over the deterministic serialization of the pairs list."""
    h = hashlib.sha256()
    for p in pairs:
        h.update(p["a"].encode())
        h.update(b"\x1f")
        h.update(p["b"].encode())
        h.update(b"\x1f")
        h.update(f"{p['cosine']:.6f}".encode())
        h.update(b"\x1e")
    return f"sha256:{h.hexdigest()}"


def _build_reference_embedder(name: str):
    if name == "model2vec":
        from runner.variants.neural_embedder import Model2VecEmbedder
        return Model2VecEmbedder()
    if name == "hashed-token":
        from runner.variants.embed_proxy import HashedTokenEmbedder
        return HashedTokenEmbedder()
    raise ValueError(f"unknown reference-embedder {name!r}")


def _canonicals_from_workload(workload_id: str) -> list[str]:
    """Extract unique oracle canonicals (preserving first-seen order)
    from a registered workload."""
    seen: dict[str, None] = {}
    for _, oracle_label in workloads.load(workload_id):
        if oracle_label not in seen:
            seen[oracle_label] = None
    return list(seen.keys())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tier-b-adversarials",
        description=__doc__.split("\n\n")[0],
    )
    p.add_argument("--canonical-source", required=True,
                   help="workload id from fixtures.workloads.LOADERS")
    p.add_argument("--reference-embedder", default="model2vec",
                   choices=["model2vec", "hashed-token"])
    p.add_argument("--cosine-threshold", type=float, default=0.85)
    p.add_argument("--out", required=True, help="output JSON file")
    args = p.parse_args(argv)

    canonicals = _canonicals_from_workload(args.canonical_source)
    embedder = _build_reference_embedder(args.reference_embedder)
    pairs = mine(canonicals, embedder, cosine_threshold=args.cosine_threshold)

    fixture = {
        "schema_version": "1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_source": args.canonical_source,
        "n_canonicals": len(canonicals),
        "reference_embedder": args.reference_embedder,
        "cosine_threshold": args.cosine_threshold,
        "n_pairs": len(pairs),
        "pairs": pairs,
        "fixture_sha256": _fixture_sha256(pairs),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, indent=2))
    print(
        f"Wrote {out} — {len(pairs)} adversarial pairs "
        f"(from {len(canonicals)} canonicals, threshold={args.cosine_threshold})"
    )
    print(f"  fixture_sha256: {fixture['fixture_sha256']}")
    if pairs:
        print(f"  top 5 hardest:")
        for pair in pairs[:5]:
            print(f"    {pair['a']:30s} <-> {pair['b']:30s} cos={pair['cosine']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
