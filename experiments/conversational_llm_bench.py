"""Conversational benchmark: multi-turn dialogue with aliases and
co-reference, with and without the proxy in front of the LLM.

Extends the single-sentence small_llm_quality_bench to test whether the
finding holds when:
  - Each input is a multi-turn dialogue, not a single sentence
  - Each entity is mentioned multiple times under different aliases
  - Co-referential expressions ("they", "the company", "both") refer
    back to prior entities — co-reference is the LLM's job, not the
    proxy's

Hypothesis going in: the proxy lift should be SMALLER on multi-turn
than on single-turn, because the LLM has conversation context that
already partially disambiguates aliases. But the proxy should still
help by reducing literal-surface-form fragmentation when the LLM is
asked to enumerate distinct entities.

Task: ask the LLM to list every distinct company mentioned in the
conversation. Compute set-F1 of the LLM's extracted entities vs the
oracle set per conversation. Aggregate as macro-F1 across conversations.

Run:
  .venv/bin/python experiments/conversational_llm_bench.py
  .venv/bin/python experiments/conversational_llm_bench.py --models llama3.2:3b
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


# Canonical name -> list of surface forms used in the conversations.
# These are the entries the proxy's mention_map normalizes from.
ALIAS_MAP_SOURCE = {
    "Apple Inc": ["AAPL", "Apple", "Apple Inc", "Apple Computer"],
    "Microsoft Corp": ["MSFT", "Microsoft", "Microsoft Corp", "Microsoft Corporation"],
    "Tesla Inc": ["TSLA", "Tesla", "Tesla Motors"],
    "Nvidia Corp": ["NVDA", "Nvidia", "NVIDIA Corp"],
    "Alphabet Inc": ["GOOGL", "Google", "Alphabet"],
    "Amazon Inc": ["AMZN", "Amazon", "Amazon.com"],
}


def build_alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in ALIAS_MAP_SOURCE.items():
        for alias in aliases:
            out[alias] = canonical
    return out


# Each conversation: list of turns + oracle set of canonical entities.
# Turns mix aliases, full names, and co-referential expressions.
CONVERSATIONS: list[dict] = [
    {
        "turns": [
            "I'm bullish on AAPL after their last earnings.",
            "Apple Inc did beat expectations. Their iPhone segment is strong.",
            "They might split the stock again.",
            "Speaking of stocks, MSFT also reported good numbers.",
            "Microsoft Corp's cloud business grew 30 percent.",
            "Both companies are now valued over 3 trillion.",
        ],
        "oracle": {"Apple Inc", "Microsoft Corp"},
    },
    {
        "turns": [
            "What do you think about TSLA right now?",
            "Tesla had a tough quarter, but Tesla Motors is still a long-term hold for me.",
            "They are still leading on autonomy.",
            "Compare that to NVDA, which keeps printing money.",
            "Nvidia's data center revenue is insane.",
        ],
        "oracle": {"Tesla Inc", "Nvidia Corp"},
    },
    {
        "turns": [
            "Google reported earnings yesterday.",
            "Alphabet's search ad business surprised to the upside.",
            "Their cloud unit also turned profitable.",
            "Amazon is going to report next week.",
            "AMZN is more about AWS than retail these days.",
            "Amazon.com still has the consumer business too.",
        ],
        "oracle": {"Alphabet Inc", "Amazon Inc"},
    },
    {
        "turns": [
            "Did you see Apple Computer's keynote?",
            "Yeah, AAPL announced a new chip family.",
            "Apple is going harder on AI features.",
            "Apple Inc seems to want everything on-device.",
        ],
        "oracle": {"Apple Inc"},
    },
    {
        "turns": [
            "Microsoft Corporation cut their Surface team.",
            "MSFT is doubling down on Azure and Copilot.",
            "Microsoft Corp's relationship with OpenAI is the real moat.",
            "They report next Tuesday.",
        ],
        "oracle": {"Microsoft Corp"},
    },
    {
        "turns": [
            "I'm watching three names this earnings season.",
            "NVDA, MSFT, and GOOGL.",
            "Nvidia for the AI tailwind.",
            "Microsoft for cloud growth.",
            "And Alphabet for the search resilience story.",
            "All three should beat estimates.",
        ],
        "oracle": {"Nvidia Corp", "Microsoft Corp", "Alphabet Inc"},
    },
    {
        "turns": [
            "Tesla Motors lowered prices in China again.",
            "TSLA stock dropped 5 percent on the news.",
            "Tesla still has margin to play with on the Model 3.",
        ],
        "oracle": {"Tesla Inc"},
    },
    {
        "turns": [
            "AAPL versus AMZN over the next decade?",
            "Apple has services and the install base.",
            "Amazon Inc has AWS and the logistics network.",
            "I'd take Apple Inc for stability, Amazon for upside.",
            "Hard to go wrong with either honestly.",
        ],
        "oracle": {"Apple Inc", "Amazon Inc"},
    },
    {
        "turns": [
            "Google Inc was an early name they used.",
            "Alphabet is the holding company now.",
            "Google is the operating subsidiary.",
            "Most people still say Google when they mean Alphabet.",
        ],
        "oracle": {"Alphabet Inc"},
    },
    {
        "turns": [
            "Nvidia and AMD are both up today.",
            "NVDA is the clear leader on AI.",
            "AMD is closing the gap on consumer GPUs.",
            "Long Nvidia Corp on the data center story.",
        ],
        "oracle": {"Nvidia Corp"},
        # Note: AMD is intentionally not in the alias map; the LLM may
        # extract it as a separate entity. Our metric only scores against
        # the oracle, so AMD is counted as a false positive if the LLM
        # extracts it. This tests whether the proxy noises up the LLM
        # (it shouldn't — proxy only touches mapped aliases).
    },
]


OLLAMA_URL = "http://localhost:11434/api/generate"

EXTRACTION_PROMPT = (
    "Read the conversation below. List every distinct company, brand, "
    "or organization mentioned. Output ONE name per line. Use a "
    "consistent canonical form (e.g. 'Apple Inc' instead of 'AAPL' or "
    "'Apple'). Do not include explanations, numbering, or other text.\n\n"
    "Conversation:\n{conversation}\n\n"
    "Companies mentioned:"
)


def pre_normalize(text: str, alias_map: dict[str, str]) -> str:
    if not alias_map:
        return text
    aliases_longest_first = sorted(alias_map, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(a) for a in aliases_longest_first) + r")\b"
    )
    return pattern.sub(lambda m: alias_map[m.group(1)], text)


def llm_extract_set(model: str, conversation_text: str,
                    timeout_s: float = 60.0) -> set[str]:
    body = json.dumps({
        "model": model,
        "prompt": EXTRACTION_PROMPT.format(conversation=conversation_text),
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 150},
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
    entities: set[str] = set()
    for line in raw.splitlines():
        line = line.strip().strip("\"'.,;:- \t*•")
        # Skip numbering prefixes ("1.", "2)", etc.)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        if not line:
            continue
        # Heuristic: split on commas in case the LLM puts them on one line
        for chunk in line.split(","):
            chunk = chunk.strip().strip("\"'.,;:- \t")
            if chunk:
                entities.add(chunk)
    return entities


def canonicalize_extracted(extracted: set[str], alias_map: dict[str, str]) -> set[str]:
    """Apply the alias map to the LLM's extractions before set comparison.
    Without this, the no-proxy condition is unfairly penalized: the LLM
    might say 'AAPL' which is correct but doesn't string-equal 'Apple Inc'.

    With canonicalization on BOTH conditions, the metric measures
    whether the LLM identified the right entities, not whether it
    happened to use the canonical name in its output."""
    return {alias_map.get(e, e) for e in extracted}


def set_prf(predicted: set[str], oracle: set[str]) -> tuple[float, float, float]:
    if not predicted and not oracle:
        return 1.0, 1.0, 1.0
    if not predicted:
        return 0.0, 0.0, 0.0
    if not oracle:
        return 0.0, 0.0, 0.0
    tp = len(predicted & oracle)
    p = tp / len(predicted)
    r = tp / len(oracle)
    f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f


def run_condition(model: str, conversations: list[dict], with_proxy: bool,
                  alias_map: dict[str, str]):
    extractions = []
    for conv in conversations:
        text = "\n".join(conv["turns"])
        if with_proxy:
            text = pre_normalize(text, alias_map)
        t0 = time.perf_counter()
        raw_set = llm_extract_set(model, text)
        elapsed = time.perf_counter() - t0
        # Canonicalize the LLM output too so we are scoring the SAME
        # canonical-form output set across conditions.
        canon_set = canonicalize_extracted(raw_set, alias_map)
        extractions.append({
            "oracle": sorted(conv["oracle"]),
            "raw": sorted(raw_set),
            "canonical": sorted(canon_set),
            "elapsed_s": elapsed,
        })
    return extractions


def aggregate(extractions: list[dict], conversations: list[dict]):
    p_total = r_total = f_total = 0.0
    for ex, conv in zip(extractions, conversations):
        p, r, f = set_prf(set(ex["canonical"]), conv["oracle"])
        p_total += p
        r_total += r
        f_total += f
    n = len(extractions)
    return p_total / n, r_total / n, f_total / n


def main(argv=None):
    parser_args = argv or sys.argv[1:]
    models = ["llama3.2:1b", "llama3.2:3b", "qwen2.5:14b"]
    if "--models" in parser_args:
        i = parser_args.index("--models")
        models = parser_args[i + 1].split(",")

    alias_map = build_alias_map()
    print(f"Workload: {len(CONVERSATIONS)} conversations, "
          f"alias map size {len(alias_map)}")
    print(f"Models: {models}")

    all_results = []
    for model in models:
        print(f"\n=== Model: {model} ===")
        for with_proxy, label in [(False, "no proxy"), (True, "with proxy")]:
            print(f"  Running {label}...")
            extractions = run_condition(model, CONVERSATIONS, with_proxy, alias_map)
            p, r, f = aggregate(extractions, CONVERSATIONS)
            total_s = sum(e["elapsed_s"] for e in extractions)
            print(f"    macro P={p:.3f} R={r:.3f} F1={f:.3f}, "
                  f"{total_s:.1f}s total")
            all_results.append({
                "model": model,
                "with_proxy": with_proxy,
                "macro_precision": p,
                "macro_recall": r,
                "macro_f1": f,
                "total_elapsed_s": total_s,
                "extractions": extractions,
            })

    print("\n" + "=" * 60)
    print("Summary — multi-turn conversational extraction (macro F1)")
    print("=" * 60)
    by_model: dict[str, dict[bool, dict]] = {}
    for r in all_results:
        by_model.setdefault(r["model"], {})[r["with_proxy"]] = r
    print(f"{'Model':16} {'no proxy':>11} {'with proxy':>12} {'Δ F1':>10}")
    for model in models:
        no_p = by_model[model][False]
        yes_p = by_model[model][True]
        d = yes_p["macro_f1"] - no_p["macro_f1"]
        print(f"{model:16} {no_p['macro_f1']:>11.4f} {yes_p['macro_f1']:>12.4f} "
              f"{d:>+10.4f}")

    out_path = (
        ROOT / "runs"
        / f"conversational_llm_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_conversations": len(CONVERSATIONS),
        "models": models,
        "alias_map_size": len(alias_map),
        "results": all_results,
    }, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
