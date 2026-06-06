"""Probe Mem0 v3 OSS on W-WIKIDATA-PROPS-style entries.

Documented finding: Mem0 v3 OSS produces extracted facts, not canonical
entity names, so it is not directly comparable to a schema-alignment
proxy on the B-cubed F1 metric. See docs/finding-mem0-comparison.md.

This script exists so anyone can re-run the probe and confirm. It uses
Ollama as the LLM backend (no paid API key required).

Setup:
  ollama pull all-minilm
  # qwen2.5vl:7b (or any chat model) should already be pulled
  .venv/bin/pip install mem0ai ollama

Run:
  .venv/bin/python experiments/mem0_baseline.py
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_memory():
    os.environ.setdefault("OPENAI_API_KEY", "dummy-not-used")
    from mem0 import Memory

    config = {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": "qwen2.5vl:7b",
                "temperature": 0.0,
                "max_tokens": 500,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {"model": "all-minilm"},
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": f"mem0_probe_{int(time.time())}",
                "path": "/tmp/mem0_probe",
                "embedding_model_dims": 384,
            },
        },
    }
    return Memory.from_config(config)


PROBE_INPUTS = [
    ("Apple Inc is a multinational technology company headquartered in Cupertino.", "Apple Inc"),
    ("AAPL is the NYSE stock ticker for Apple Inc.", "Apple Inc"),
    ("Apple Computer was an early name for Apple Inc.", "Apple Inc"),
    ("An apple is a fruit grown in temperate orchards worldwide.", "apple_fruit"),
    ("Apple Records is a record label founded by The Beatles.", "Apple Records"),
    ("Microsoft Corporation is an American technology company.", "Microsoft Corp"),
    ("MSFT is the NASDAQ ticker for Microsoft Corporation.", "Microsoft Corp"),
    ("Microsoft Office is a productivity suite.", "Microsoft Office"),
    ("Ford Mustang is an American muscle car.", "Ford Mustang"),
    ("A mustang is a feral domesticated horse.", "mustang_horse"),
]


def main(argv=None):
    print("Building Memory (Ollama backend)...")
    m = build_memory()
    print("Ready. Running probe on 10 inputs.")

    results = []
    for sentence, expected_canonical in PROBE_INPUTS:
        t0 = time.perf_counter()
        out = m.add(sentence, user_id="probe_user")
        elapsed_s = time.perf_counter() - t0
        memories = out.get("results", [])
        extracted = [str(mem.get("memory", "")) for mem in memories]
        results.append({
            "input": sentence,
            "expected_canonical": expected_canonical,
            "elapsed_seconds": elapsed_s,
            "extracted_count": len(extracted),
            "extracted": extracted,
        })
        print(
            f"  ({elapsed_s:>5.1f}s) {sentence[:60]!r:62s} -> "
            f"{len(extracted)} extracted"
        )

    out_dir = ROOT / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir / f"mem0_baseline_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_inputs": len(PROBE_INPUTS),
        "results": results,
        "note": (
            "Mem0 v3 OSS outputs are extracted facts in sentence form, "
            "not canonical entity names. See "
            "docs/finding-mem0-comparison.md for the analysis."
        ),
    }, indent=2))
    print(f"\nWrote {out_path}")
    print("Finding: Mem0 OSS extracted facts (not canonicals).")
    print("See docs/finding-mem0-comparison.md.")


if __name__ == "__main__":
    main()
