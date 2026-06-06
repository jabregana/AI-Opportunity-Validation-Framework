"""Conversational LLM benchmark for the Anthropic API.

Mirror of experiments/conversational_llm_bench.py but calls Claude via
the Anthropic API instead of Ollama. Reuses the SAME 10 conversations,
the SAME alias map, the SAME extraction prompt, and the SAME scoring
logic (canonicalize-extracted-outputs before set comparison so both
conditions are scored on the same normalized output space).

Lets the Opus 4.7 result slot directly into the existing
multi-turn table alongside the local 1B/3B/14B runs.

Requires:
  export ANTHROPIC_API_KEY=sk-ant-...

Run:
  ! ANTHROPIC_API_KEY=... .venv/bin/python experiments/claude_api_conversational_bench.py
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.conversational_llm_bench import (
    CONVERSATIONS,
    EXTRACTION_PROMPT,
    aggregate,
    build_alias_map,
    canonicalize_extracted,
    pre_normalize,
    set_prf,
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def claude_extract_set(model: str, api_key: str, conversation_text: str,
                       timeout_s: float = 60.0) -> set[str]:
    # max_tokens raised to 200: the conversational extractor must list
    # several entity names, often on separate lines. The single-token
    # entity bench uses 30; here we need room for ~3-6 names.
    body = json.dumps({
        "model": model,
        "max_tokens": 200,
        "messages": [
            {"role": "user", "content": EXTRACTION_PROMPT.format(
                conversation=conversation_text
            )},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Anthropic API HTTP {e.code}: {body_text}"
        ) from e

    text_blocks = [
        b.get("text", "") for b in payload.get("content", [])
        if b.get("type") == "text"
    ]
    raw = "".join(text_blocks).strip()

    # Same parsing as the Ollama bench: split on lines and commas,
    # strip numbering and surrounding punctuation.
    import re as _re
    entities: set[str] = set()
    for line in raw.splitlines():
        line = line.strip().strip("\"'.,;:- \t*•")
        line = _re.sub(r"^\d+[\.\)]\s*", "", line)
        if not line:
            continue
        for chunk in line.split(","):
            chunk = chunk.strip().strip("\"'.,;:- \t")
            if chunk:
                entities.add(chunk)
    return entities


def run_condition(model: str, api_key: str, conversations: list[dict],
                  with_proxy: bool, alias_map: dict[str, str]):
    extractions = []
    for conv in conversations:
        text = "\n".join(conv["turns"])
        if with_proxy:
            text = pre_normalize(text, alias_map)
        t0 = time.perf_counter()
        raw_set = claude_extract_set(model, api_key, text)
        elapsed = time.perf_counter() - t0
        canon_set = canonicalize_extracted(raw_set, alias_map)
        extractions.append({
            "oracle": sorted(conv["oracle"]),
            "raw": sorted(raw_set),
            "canonical": sorted(canon_set),
            "elapsed_s": elapsed,
        })
    return extractions


def main(argv=None):
    parser = argparse.ArgumentParser(prog="claude-api-conversational-bench")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"claude_api_conversational_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. "
              "Run `export ANTHROPIC_API_KEY=sk-ant-...`")
        return 1

    alias_map = build_alias_map()
    print(f"Workload: {len(CONVERSATIONS)} conversations, "
          f"alias map size {len(alias_map)}")
    print(f"Model: {args.model} (Anthropic API)")

    all_results = []
    for with_proxy, label in [(False, "no proxy"), (True, "with proxy")]:
        print(f"\n  Running {label}...")
        extractions = run_condition(args.model, api_key, CONVERSATIONS,
                                    with_proxy, alias_map)
        p, r, f = aggregate(extractions, CONVERSATIONS)
        total_s = sum(e["elapsed_s"] for e in extractions)
        per_conv_s = total_s / len(extractions)
        print(f"    macro P={p:.3f} R={r:.3f} F1={f:.3f}, "
              f"{total_s:.1f}s total ({per_conv_s*1000:.0f}ms/conv)")
        all_results.append({
            "model": args.model,
            "with_proxy": with_proxy,
            "macro_precision": p,
            "macro_recall": r,
            "macro_f1": f,
            "total_elapsed_s": total_s,
            "ms_per_conversation": per_conv_s * 1000,
            "extractions": extractions,
        })

    print("\n" + "=" * 60)
    print(f"Summary for {args.model}")
    print("=" * 60)
    no_p, yes_p = all_results
    print(f"  no proxy:    macro F1 = {no_p['macro_f1']:.4f}, "
          f"{no_p['ms_per_conversation']:.0f}ms/conv")
    print(f"  with proxy:  macro F1 = {yes_p['macro_f1']:.4f}, "
          f"{yes_p['ms_per_conversation']:.0f}ms/conv")
    print(f"  Δ macro F1:  {yes_p['macro_f1'] - no_p['macro_f1']:+.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "provider": "anthropic",
        "n_conversations": len(CONVERSATIONS),
        "alias_map_size": len(alias_map),
        "results": all_results,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
