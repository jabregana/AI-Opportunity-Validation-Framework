"""Extend the small_llm_quality_bench ladder past 33B using the
Anthropic API. Tests Claude Opus 4.7 (frontier-tier) on the exact same
entity-extraction workload and prompt the Ollama bench uses, so the
result slots in directly alongside the 1.2B / 3.2B / 8B / 14.8B / 33.5B
local-model ladder.

Requires:
  export ANTHROPIC_API_KEY=sk-ant-...

Run:
  .venv/bin/python experiments/claude_api_quality_bench.py
  .venv/bin/python experiments/claude_api_quality_bench.py --model claude-haiku-4-5-20251001
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.metrics import alignment
from experiments.small_llm_quality_bench import (
    EXTRACTION_PROMPT,
    build_alias_map,
    build_workload,
    pre_normalize,
)


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def claude_extract(model: str, api_key: str, text: str,
                   timeout_s: float = 60.0) -> str:
    # Note: temperature is deprecated on Claude 4.x and produces a 400.
    # Determinism on Claude 4.x relies on the model's own sampling
    # discipline at the API level rather than a client-set temperature.
    body = json.dumps({
        "model": model,
        "max_tokens": 30,
        "messages": [
            {"role": "user", "content": EXTRACTION_PROMPT.format(text=text)},
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
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Anthropic API HTTP {e.code}: {body}\n"
            f"Request body sent: model={model!r}, text={text[:80]!r}"
        ) from e
    blocks = payload.get("content", [])
    text_blocks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    raw = "".join(text_blocks).strip()
    first_line = raw.split("\n")[0].strip()
    cleaned = first_line.strip("\"'.,;: \t")
    return cleaned or "<EMPTY>"


def run_condition(model: str, api_key: str, utterances: list[str],
                  with_proxy: bool, alias_map: dict[str, str]):
    inputs = [pre_normalize(u, alias_map) if with_proxy else u for u in utterances]
    extracted: list[str] = []
    t0 = time.perf_counter()
    for inp in inputs:
        extracted.append(claude_extract(model, api_key, inp))
    return extracted, time.perf_counter() - t0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="claude-api-quality-bench")
    parser.add_argument("--model", default="claude-opus-4-7")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"claude_api_quality_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Run `export ANTHROPIC_API_KEY=sk-ant-...`")
        return 1

    print(f"Building workload...")
    workload = build_workload()
    print(f"  {len(workload)} utterances")
    alias_map = build_alias_map()

    utterances = [u for u, _, _ in workload]
    oracle = [(u, canonical) for u, canonical, _ in workload]

    print(f"\n=== Model: {args.model} (Anthropic API) ===")
    results = []
    for with_proxy, label in [(False, "no proxy"), (True, "with proxy")]:
        print(f"  Running {label}...")
        extracted, elapsed = run_condition(
            args.model, api_key, utterances, with_proxy, alias_map
        )
        preds = list(zip(utterances, extracted))
        bcubed = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
        unique_outputs = len(set(extracted))
        print(f"    B-cubed F1 = {bcubed:.4f}, "
              f"{unique_outputs} unique outputs (ideal: 6), "
              f"{elapsed:.1f}s ({elapsed/len(utterances)*1000:.0f}ms/call)")
        results.append({
            "model": args.model,
            "with_proxy": with_proxy,
            "bcubed_f1": bcubed,
            "unique_outputs": unique_outputs,
            "ideal_outputs": 6,
            "elapsed_s": elapsed,
            "ms_per_call": elapsed / len(utterances) * 1000,
            "extractions": [
                {"utterance": u, "oracle": o, "alias": a, "llm_output": e}
                for (u, o, a), e in zip(workload, extracted)
            ],
        })

    no_p, yes_p = results
    print("\n" + "=" * 70)
    print(f"Summary for {args.model}")
    print("=" * 70)
    print(f"  no proxy:    B-cubed = {no_p['bcubed_f1']:.4f}, "
          f"{no_p['unique_outputs']} unique outputs, "
          f"{no_p['ms_per_call']:.0f}ms/call")
    print(f"  with proxy:  B-cubed = {yes_p['bcubed_f1']:.4f}, "
          f"{yes_p['unique_outputs']} unique outputs, "
          f"{yes_p['ms_per_call']:.0f}ms/call")
    print(f"  Δ B-cubed:   {yes_p['bcubed_f1'] - no_p['bcubed_f1']:+.4f}")
    print(f"  Speedup:     {no_p['ms_per_call'] / yes_p['ms_per_call']:.2f}x")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "provider": "anthropic",
        "results": results,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
