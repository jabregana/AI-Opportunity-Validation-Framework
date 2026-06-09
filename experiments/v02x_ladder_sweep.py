"""LLM ladder sweep for v0.2.x graph-topology variants.

Runs the Graphiti F1 benchmark across a (variant x LLM-model) matrix
so the framework can compare variant performance across the local
LLM ladder. Output: a single comparison table aligning each
(variant, model) cell with reduction% / F1 preservation% / wall time.

Per docs/benchmark-methodology.md, each cell should be run at
multiple seeds for CI reporting; this script accepts --n-seeds and
loops the matrix once per seed.

Usage:
  # Smoke test (1 variant, 1 model, 1 seed; ~30 min on Ollama)
  python experiments/v02x_ladder_sweep.py \\
      --variants gc-v0.2.5-comprehensive-graph-tuned \\
      --models phi3:mini \\
      --n-seeds 1

  # Full ladder (6 variants x 4 models x 3 seeds = 72 runs; ~36 hours)
  python experiments/v02x_ladder_sweep.py \\
      --variants gc-v0.2.0-component-isolation,gc-v0.2.1-temporal-validity,gc-v0.2.2-activation-decay,gc-v0.2.3-evidence-count,gc-v0.2.4-supersession-tombstone,gc-v0.2.5-comprehensive-graph-tuned \\
      --models phi3:mini,llama3.1:8b,qwen2.5:14b,gemma2:9b \\
      --n-seeds 3

  # Practical first ladder (3 variants x 2 models x 1 seed; ~3 hours)
  python experiments/v02x_ladder_sweep.py \\
      --variants gc-v0.2.5-comprehensive-graph-tuned,gc-v0.2.0-component-isolation,b-raw-no-gc \\
      --models phi3:mini,llama3.1:8b \\
      --n-seeds 1

Prerequisites:
  - Neo4j running locally (docker start graphiti-neo4j or equivalent)
  - graphiti-core installed (pip install graphiti-core)
  - Ollama running with all requested models pulled
  - all-minilm:latest pulled for embedding (default embedder)
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_one_cell(
    variant: str,
    model: str,
    seed: int,
    n_pairs: int,
    out_dir: Path,
    neo4j_uri: str,
    neo4j_password: str,
) -> dict:
    """Run one (variant, model, seed) cell of the matrix.

    Calls experiments/graphiti_retrieval_f1_benchmark.py as a subprocess
    so each run gets its own clean state. Returns the parsed artifact
    or an error dict.
    """
    cell_out = out_dir / f"{variant}_{model.replace(':', '-')}_seed{seed}.json"
    cmd = [
        sys.executable,
        str(ROOT / "experiments" / "graphiti_retrieval_f1_benchmark.py"),
        "--n-pairs", str(n_pairs),
        "--aged-fraction", "0.4",
        "--variant", variant,
        "--llm-provider", "ollama",
        "--ollama-llm-model", model,
        "--neo4j-uri", neo4j_uri,
        "--neo4j-password", neo4j_password,
        "--out", str(cell_out),
    ]
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
        )
        wall = time.time() - t0
        if result.returncode != 0:
            return {
                "variant": variant, "model": model, "seed": seed,
                "status": "FAIL",
                "wall_seconds": wall,
                "error": result.stderr[-500:] if result.stderr else "unknown",
            }
        if cell_out.exists():
            artifact = json.loads(cell_out.read_text())
            metrics = artifact.get("metrics", {})
            gates = artifact.get("gates", {})
            return {
                "variant": variant, "model": model, "seed": seed,
                "status": "OK",
                "wall_seconds": wall,
                "reduction_pct": metrics.get("reduction_pct", 0.0),
                "f1_before": metrics.get("retrieval_f1_before", 0.0),
                "f1_after": metrics.get("retrieval_f1_after", 0.0),
                "f1_preservation_pct": gates.get("UC-GC-RETRIEVAL", {}).get("value", 0.0),
                "gate_status": gates.get("UC-GC-RETRIEVAL", {}).get("status", "?"),
                "artifact_path": str(cell_out),
            }
        return {
            "variant": variant, "model": model, "seed": seed,
            "status": "NO_ARTIFACT", "wall_seconds": wall,
        }
    except subprocess.TimeoutExpired:
        return {
            "variant": variant, "model": model, "seed": seed,
            "status": "TIMEOUT", "wall_seconds": time.time() - t0,
        }


def main():
    p = argparse.ArgumentParser(prog="v02x-ladder-sweep")
    p.add_argument("--variants", required=True,
                   help="Comma-separated variant ids")
    p.add_argument("--models", required=True,
                   help="Comma-separated Ollama model names")
    p.add_argument("--n-seeds", type=int, default=1,
                   help="Number of seeded runs per (variant, model) cell")
    p.add_argument("--n-pairs", type=int, default=20,
                   help="SQuAD pairs per benchmark run")
    p.add_argument("--seeds", default="42,123,456",
                   help="Comma-separated seed values (uses first --n-seeds)")
    p.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j-password", default="changeme")
    p.add_argument("--out-dir", default="runs/v02x_ladder")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the matrix without executing")
    args = p.parse_args()

    variants = [v.strip() for v in args.variants.split(",")]
    models = [m.strip() for m in args.models.split(",")]
    seeds = [int(s.strip()) for s in args.seeds.split(",")][:args.n_seeds]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_cells = len(variants) * len(models) * len(seeds)
    estimated_minutes = total_cells * 20  # rough estimate; depends on model + Graphiti

    print("=" * 78)
    print(f"v0.2.x LLM ladder sweep")
    print("=" * 78)
    print(f"Variants ({len(variants)}): {variants}")
    print(f"Models   ({len(models)}): {models}")
    print(f"Seeds    ({len(seeds)}): {seeds}")
    print(f"Total cells: {total_cells}")
    print(f"Est. wall time: ~{estimated_minutes // 60}h {estimated_minutes % 60}m")
    print(f"Output dir: {out_dir}")
    print()

    if args.dry_run:
        print("--- DRY RUN: cells that would execute ---")
        for variant in variants:
            for model in models:
                for seed in seeds:
                    print(f"  {variant} x {model} x seed={seed}")
        return 0

    results: list[dict] = []
    for i, variant in enumerate(variants):
        for j, model in enumerate(models):
            for k, seed in enumerate(seeds):
                cell_num = i * len(models) * len(seeds) + j * len(seeds) + k + 1
                print(f"[{cell_num}/{total_cells}] {variant} x {model} x seed={seed}")
                cell = _run_one_cell(
                    variant=variant, model=model, seed=seed,
                    n_pairs=args.n_pairs, out_dir=out_dir,
                    neo4j_uri=args.neo4j_uri,
                    neo4j_password=args.neo4j_password,
                )
                results.append(cell)
                if cell["status"] == "OK":
                    print(f"    OK: reduction={cell['reduction_pct']:.1f}%, "
                          f"F1 preservation={cell['f1_preservation_pct']:.1f}%, "
                          f"gate={cell['gate_status']}, wall={cell['wall_seconds']:.0f}s")
                else:
                    print(f"    {cell['status']}: wall={cell['wall_seconds']:.0f}s")

    summary_path = out_dir / "ladder_summary.json"
    summary_path.write_text(json.dumps({
        "variants": variants,
        "models": models,
        "seeds": seeds,
        "n_pairs": args.n_pairs,
        "results": results,
    }, indent=2))

    print()
    print("=" * 78)
    print(f"Ladder summary: {summary_path}")
    print("=" * 78)
    print(f"{'variant':40s} {'model':18s} {'seed':>5s} {'reduction':>10s} {'F1 pres':>10s} {'gate':>6s}")
    for r in results:
        if r["status"] == "OK":
            print(f"{r['variant']:40s} {r['model']:18s} {r['seed']:>5d} "
                  f"{r['reduction_pct']:>9.1f}% {r['f1_preservation_pct']:>9.1f}% "
                  f"{r['gate_status']:>6s}")
        else:
            print(f"{r['variant']:40s} {r['model']:18s} {r['seed']:>5d} "
                  f"{r['status']}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
