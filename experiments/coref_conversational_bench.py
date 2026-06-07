"""Conversational benchmark with co-reference resolver upstream of
the proxy.

Tests whether running LLMCorefResolver on the conversation text
BEFORE the proxy normalizes aliases closes the gap flagged in
docs/finding-conversational-llm.md: the proxy lift shrinks on
multi-turn because pronouns ("they", "the company") carry entity
references the proxy can't see.

Four conditions on the same 10 conversations from conversational_llm_bench,
all run against llama3.1:8b:

  A. raw (baseline):     no preprocessor, no proxy
  B. proxy only:          mention_map only (the prior conversational result)
  C. coref only:          LLMCorefResolver only, no proxy
  D. coref + proxy:       resolver upstream, mention_map downstream

Hypothesis: C improves over A (rewrites pronouns to entity names so
the downstream LLM sees explicit mentions). D improves over both B and
C because pronouns get resolved AND aliases get canonicalized; the
chain compounds.

Run:
  .venv/bin/python experiments/coref_conversational_bench.py
"""
from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.conversational_llm_bench import (
    CONVERSATIONS,
    aggregate,
    build_alias_map,
    canonicalize_extracted,
    llm_extract_set,
    pre_normalize,
)
from runner.service.preprocessors import LLMCorefResolver


def run_condition(model: str, conversations: list[dict], label: str,
                  preprocess_chain, alias_map: dict[str, str]):
    """preprocess_chain is a list of callables applied in order to each
    conversation text."""
    extractions = []
    for conv in conversations:
        text = "\n".join(conv["turns"])
        for step in preprocess_chain:
            text = step(text)
        t0 = time.perf_counter()
        raw_set = llm_extract_set(model, text)
        elapsed = time.perf_counter() - t0
        canon_set = canonicalize_extracted(raw_set, alias_map)
        extractions.append({
            "oracle": sorted(conv["oracle"]),
            "raw": sorted(raw_set),
            "canonical": sorted(canon_set),
            "elapsed_s": elapsed,
        })
    p, r, f = aggregate(extractions, conversations)
    total_s = sum(e["elapsed_s"] for e in extractions)
    print(f"  {label:24} P={p:.3f} R={r:.3f} F1={f:.3f}, "
          f"{total_s:.1f}s extract time")
    return {
        "label": label,
        "macro_precision": p,
        "macro_recall": r,
        "macro_f1": f,
        "total_extract_seconds": total_s,
        "extractions": extractions,
    }


def main():
    model = "llama3.1:8b"
    alias_map = build_alias_map()
    resolver = LLMCorefResolver(model=model)

    print(f"Workload: {len(CONVERSATIONS)} conversations")
    print(f"Model (extraction + coref): {model}")
    print(f"Alias map: {len(alias_map)} aliases\n")

    def passthrough(t):
        return t

    def map_only(t):
        return pre_normalize(t, alias_map)

    def coref_only(t):
        return resolver(t)

    def coref_then_map(t):
        return pre_normalize(resolver(t), alias_map)

    results = []
    print("Running conditions...")
    results.append(run_condition(model, CONVERSATIONS,
                                 "A_raw", [passthrough], alias_map))
    results.append(run_condition(model, CONVERSATIONS,
                                 "B_proxy_only", [map_only], alias_map))
    results.append(run_condition(model, CONVERSATIONS,
                                 "C_coref_only", [coref_only], alias_map))
    results.append(run_condition(model, CONVERSATIONS,
                                 "D_coref_then_proxy",
                                 [coref_then_map], alias_map))

    by_label = {r["label"]: r for r in results}
    a = by_label["A_raw"]["macro_f1"]
    b = by_label["B_proxy_only"]["macro_f1"]
    c = by_label["C_coref_only"]["macro_f1"]
    d = by_label["D_coref_then_proxy"]["macro_f1"]

    print("\n" + "=" * 60)
    print("Summary — co-reference upstream of proxy on multi-turn dialog")
    print("=" * 60)
    print(f"  A raw (baseline):         F1 = {a:.4f}")
    print(f"  B proxy only:             F1 = {b:.4f}   (Δ vs A = {b - a:+.4f})")
    print(f"  C coref only:             F1 = {c:.4f}   (Δ vs A = {c - a:+.4f})")
    print(f"  D coref + proxy:          F1 = {d:.4f}   (Δ vs A = {d - a:+.4f}, "
          f"vs B = {d - b:+.4f}, vs C = {d - c:+.4f})")

    if d > b + 0.02:
        verdict = (f"Coref + proxy IMPROVES over proxy-only by {d - b:+.4f} — "
                   f"the conversational gap is partly closed.")
    elif d < b - 0.02:
        verdict = (f"Coref + proxy HURTS vs proxy-only ({d - b:+.4f}) — "
                   f"the resolver introduced noise.")
    else:
        verdict = (f"Coref + proxy is NEUTRAL vs proxy-only — "
                   f"the resolver doesn't help on this workload.")
    print(f"\nVerdict: {verdict}")

    out_path = (
        ROOT / "runs"
        / f"coref_conversational_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "n_conversations": len(CONVERSATIONS),
        "alias_map_size": len(alias_map),
        "results": results,
        "verdict": verdict,
    }, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
