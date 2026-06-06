"""Small-LLM quality benchmark: does the proxy's pre-normalization
make a small LLM's entity extraction coherent, where it would
otherwise fragment?

Thesis (from the explorations summary):
  - Small LLMs (1-3B params) do not reliably know that AAPL, Apple,
    Apple Inc, Apple Computer are the same entity. Without help they
    produce fragmented entity extractions.
  - Large LLMs (14B+) do know this. They canonicalize well on their
    own, so the proxy's value for them is latency, cost, and
    determinism, not quality.
  - Pre-normalizing the input text via the proxy (using a domain alias
    map, the Mem0PreNormalized pattern) should produce the largest
    quality lift on the smallest LLM and a diminishing lift as model
    size grows.

This script measures that prediction directly. For each LLM in a size
ladder and each (with_proxy, without_proxy) condition, it asks the
LLM to extract the main entity from each utterance, clusters the
extracted entities, and reports B-cubed F1 against the oracle.

The "proxy" in this benchmark is the static alias-map slot of
Mem0PreNormalized (the realistic v0.5.x integration shape for known
domain aliases). No embedding-based normalization is needed because
the alias map is the domain knowledge.

Run:
  .venv/bin/python experiments/small_llm_quality_bench.py
"""
from __future__ import annotations
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.metrics import alignment


# Six well-known public companies. Each has 5 surface aliases the LLM
# might encounter in a real conversational stream. The CANONICAL form
# (key) is what the alias map normalizes everything to.
ENTITIES: dict[str, list[str]] = {
    "Apple Inc": ["AAPL", "Apple", "Apple Inc", "Apple Inc.", "Apple Computer"],
    "Microsoft Corp": ["MSFT", "Microsoft", "Microsoft Corp", "Microsoft Corporation", "MSFT Corp"],
    "Tesla Inc": ["TSLA", "Tesla", "Tesla Motors", "Tesla Inc", "Tesla Inc."],
    "Nvidia Corp": ["NVDA", "Nvidia", "NVIDIA Corp", "Nvidia Corporation", "NVDA Inc"],
    "Alphabet Inc": ["GOOGL", "Google", "Alphabet", "Alphabet Inc", "Google LLC"],
    "Amazon Inc": ["AMZN", "Amazon", "Amazon.com", "Amazon Inc", "Amazon Inc."],
}

# Five short conversational templates. Each entity uses every template
# once (with a different alias each time), giving 6 * 5 = 30 utterances.
TEMPLATES = [
    "Bought {alias} today.",
    "{alias} reported earnings.",
    "Watching {alias} closely.",
    "Sold {alias} this morning.",
    "{alias} is up 5 percent.",
]

# Five LLM sizes spanning a 1B → 32B ladder (all local Ollama).
# Original three (1B/3B/14B) plus llama3.1:8b for the mid-tier and
# qwen2.5vl:32b for the very large end. To restrict to a subset for
# faster runs, pass --models on the CLI.
MODELS = [
    "llama3.2:1b",
    "llama3.2:3b",
    "llama3.1:8b",
    "qwen2.5:14b",
    "qwen2.5vl:32b",
]

OLLAMA_URL = "http://localhost:11434/api/generate"

EXTRACTION_PROMPT = (
    "You are an entity extractor. Read the sentence and return the "
    "name of the main company, product, or entity mentioned. Reply "
    "with ONLY the entity name (e.g. 'Apple Inc' or 'Microsoft'). "
    "Do not add explanation, punctuation, or extra text.\n\n"
    "Sentence: {text}\n"
    "Entity:"
)


def build_workload() -> list[tuple[str, str, str]]:
    """Return [(utterance, oracle_canonical, alias_used)]."""
    out = []
    for canonical, aliases in ENTITIES.items():
        assert len(aliases) == len(TEMPLATES), (
            f"{canonical}: need {len(TEMPLATES)} aliases, got {len(aliases)}"
        )
        for alias, template in zip(aliases, TEMPLATES):
            out.append((template.format(alias=alias), canonical, alias))
    return out


def build_alias_map() -> dict[str, str]:
    """Mention-map for Mem0PreNormalized-style substitution."""
    out: dict[str, str] = {}
    for canonical, aliases in ENTITIES.items():
        for alias in aliases:
            out[alias] = canonical
    return out


def pre_normalize(text: str, alias_map: dict[str, str]) -> str:
    """Single-pass regex with longest-first alternation, matching the
    Mem0PreNormalized implementation in runner/service/integrations/mem0.py."""
    if not alias_map:
        return text
    aliases_longest_first = sorted(alias_map, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(a) for a in aliases_longest_first) + r")\b"
    )
    return pattern.sub(lambda m: alias_map[m.group(1)], text)


def llm_extract(model: str, text: str, timeout_s: float = 30.0) -> str:
    """Call Ollama and return the LLM's entity extraction (stripped)."""
    body = json.dumps({
        "model": model,
        "prompt": EXTRACTION_PROMPT.format(text=text),
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 30},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raw = payload.get("response", "").strip()
    # LLMs sometimes return quoted strings or trailing periods; clean it.
    first_line = raw.split("\n")[0].strip()
    cleaned = first_line.strip("\"'.,;: \t")
    return cleaned or "<EMPTY>"


def run_condition(model: str, utterances: list[str], with_proxy: bool,
                  alias_map: dict[str, str]) -> tuple[list[str], float]:
    """Run all utterances through the LLM. Return (extracted_list, elapsed_s)."""
    inputs = [pre_normalize(u, alias_map) if with_proxy else u for u in utterances]
    extracted: list[str] = []
    t0 = time.perf_counter()
    for inp in inputs:
        extracted.append(llm_extract(model, inp))
    return extracted, time.perf_counter() - t0


def main(argv=None):
    parser_args = argv or sys.argv[1:]
    models = MODELS
    if "--models" in parser_args:
        i = parser_args.index("--models")
        models = parser_args[i + 1].split(",")
    print("Building workload...")
    workload = build_workload()
    print(f"  {len(workload)} utterances across {len(ENTITIES)} oracle entities")
    alias_map = build_alias_map()
    print(f"  alias map: {len(alias_map)} aliases")

    utterances = [u for u, _, _ in workload]
    oracle = [(u, canonical) for u, canonical, _ in workload]

    all_results = []
    for model in models:
        print(f"\n=== Model: {model} ===")
        for with_proxy, label in [(False, "no proxy"), (True, "with proxy")]:
            print(f"  Running {label}...")
            extracted, elapsed = run_condition(model, utterances, with_proxy, alias_map)
            preds = list(zip(utterances, extracted))
            bcubed = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
            unique_outputs = len(set(extracted))
            print(f"    B-cubed F1 = {bcubed:.4f}, "
                  f"{unique_outputs} unique outputs (ideal: {len(ENTITIES)}), "
                  f"{elapsed:.1f}s ({elapsed/len(utterances)*1000:.0f}ms/call)")
            all_results.append({
                "model": model,
                "with_proxy": with_proxy,
                "bcubed_f1": bcubed,
                "unique_outputs": unique_outputs,
                "ideal_outputs": len(ENTITIES),
                "elapsed_s": elapsed,
                "ms_per_call": elapsed / len(utterances) * 1000,
                "extractions": [
                    {"utterance": u, "oracle": o, "alias": a, "llm_output": e}
                    for (u, o, a), e in zip(workload, extracted)
                ],
            })

    print("\n" + "=" * 70)
    print("Summary — quality lift from pre-normalization across model sizes")
    print("=" * 70)
    print(f"{'Model':16} {'no proxy':>11} {'with proxy':>12} {'Δ B-cubed':>11} {'Δ unique':>10}")
    by_model: dict[str, dict[bool, dict]] = {}
    for r in all_results:
        by_model.setdefault(r["model"], {})[r["with_proxy"]] = r
    for model in models:
        no_p = by_model[model][False]
        yes_p = by_model[model][True]
        d_bc = yes_p["bcubed_f1"] - no_p["bcubed_f1"]
        d_uniq = yes_p["unique_outputs"] - no_p["unique_outputs"]
        print(f"{model:16} {no_p['bcubed_f1']:>11.4f} {yes_p['bcubed_f1']:>12.4f} "
              f"{d_bc:>+11.4f} {d_uniq:>+10d}")

    out_path = (
        ROOT / "runs"
        / f"small_llm_quality_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_utterances": len(workload),
        "n_oracle_entities": len(ENTITIES),
        "models": models,
        "alias_map_size": len(alias_map),
        "results": all_results,
    }, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
