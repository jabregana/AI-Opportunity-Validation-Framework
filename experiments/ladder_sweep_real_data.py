"""Run the scaled-tweet bench across the full LLM ladder on real data.

Reuses the same 269-tweet workload from scale_tweet_bench. For each
model in the local Ollama ladder (1.2B, 3.2B, 14.8B, 33.5B), runs
both conditions and computes per-tweet binary metrics. Skips the
already-completed 8B run (its result file is read in to fill that
ladder slot). For the frontier tier (Claude Opus 4.7 via API), set
ANTHROPIC_API_KEY and use --include-opus.

Output: a single ladder table aligning each model with proxy on/off
accuracy + canonical-output rate + surface-variant count, plus
bootstrap CIs on the per-model diff.

Run:
  .venv/bin/python experiments/ladder_sweep_real_data.py
  ! ANTHROPIC_API_KEY=... .venv/bin/python experiments/ladder_sweep_real_data.py --include-opus
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

from experiments.real_dataset_bench import (
    build_alias_map,
    canonicalize_for_scoring,
    load_filtered_tweets,
)
from experiments.small_llm_quality_bench import (
    EXTRACTION_PROMPT,
    llm_extract as ollama_extract,
    pre_normalize,
)
from runner.metrics.stats import paired_bootstrap


LOCAL_MODELS = [
    "llama3.2:1b",         # 1.2B (llama family)
    "llama3.2:3b",         # 3.2B (llama family)
    "qwen2.5:3b",          # 3.1B (qwen family)
    "phi3:mini",           # 3.8B (microsoft phi family)
    "mistral:7b",          # 7.2B (mistral family) — must be pulled
    "llama3.1:8b",         # 8.0B (llama family)
    "qwen2.5vl:7b",        # 8.3B (qwen-vl family)
    "gemma2:9b",           # 9.2B (gemma family) — must be pulled
    "qwen2.5:14b",         # 14.8B (qwen family)
    "qwen2.5vl:32b",       # 33.5B (qwen-vl family)
]
OPUS_MODEL = "claude-opus-4-7"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def _clean(raw: str) -> str:
    """Common cleanup: take first line, strip quote/punct."""
    first_line = raw.strip().split("\n")[0].strip()
    return first_line.strip("\"'.,;: \t") or "<EMPTY>"


def _post_with_retry(req: urllib.request.Request, timeout_s: float,
                     max_retries: int = 3, label: str = "API") -> dict:
    """POST with exponential backoff on transient network errors.
    HTTPError is propagated (likely a model/auth issue, not transient)."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise  # do not retry on 4xx/5xx — let caller decide
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 1, 2, 4 seconds
                print(f"  {label} transient error (attempt {attempt + 1}/{max_retries + 1}): "
                      f"{type(e).__name__}; retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"{label} failed after {max_retries + 1} attempts: "
                f"{type(last_exc).__name__}: {last_exc}"
            ) from last_exc


def claude_extract(model: str, api_key: str, text: str,
                   timeout_s: float = 120.0) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 30,
        "messages": [
            {"role": "user", "content": EXTRACTION_PROMPT.format(text=text)},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        payload = _post_with_retry(req, timeout_s, label="Anthropic")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API HTTP {e.code}: {body_text}") from e
    blocks = payload.get("content", [])
    text_blocks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return _clean("".join(text_blocks))


def openai_extract(model: str, api_key: str, text: str,
                   timeout_s: float = 120.0) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 30,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": EXTRACTION_PROMPT.format(text=text)},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL, data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        payload = _post_with_retry(req, timeout_s, label="OpenAI")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {e.code}: {body_text}") from e
    choices = payload.get("choices", [])
    if not choices:
        return "<EMPTY>"
    return _clean(choices[0]["message"]["content"])


def gemini_extract(model: str, api_key: str, text: str,
                   timeout_s: float = 120.0) -> str:
    url = GEMINI_URL_TEMPLATE.format(model=model, key=api_key)
    # Gemini 2.5 Pro REQUIRES thinking mode (the API rejects
    # thinkingBudget=0 with "This model only works in thinking mode").
    # Gemini 2.5 Flash supports thinkingBudget=0. Strategy:
    #   - For 2.5 Pro: allow thinking, give a generous output budget
    #     (4096) so thinking + actual answer both fit.
    #   - For 2.5 Flash: disable thinking explicitly for fast cheap calls.
    #   - For 1.5 and earlier: no thinking config needed.
    if "2.5-flash" in model:
        config = {"maxOutputTokens": 200, "temperature": 0,
                  "thinkingConfig": {"thinkingBudget": 0}}
    elif "2.5-pro" in model or "2.5" in model:
        config = {"maxOutputTokens": 4096, "temperature": 0}
    else:
        config = {"maxOutputTokens": 200, "temperature": 0}
    body = json.dumps({
        "contents": [
            {"parts": [{"text": EXTRACTION_PROMPT.format(text=text)}]}
        ],
        "generationConfig": config,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        payload = _post_with_retry(req, timeout_s, label="Gemini")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API HTTP {e.code}: {body_text}") from e
    candidates = payload.get("candidates", [])
    if not candidates:
        return "<EMPTY>"
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        # Could be MAX_TOKENS with all budget consumed by thinking, or
        # SAFETY filter. Return EMPTY so downstream metric reflects it.
        return "<EMPTY>"
    return _clean(parts[0].get("text", ""))


def _route_extractor(model: str):
    """Return (provider_name, extractor_fn, api_key_env_var) for a model."""
    if model.startswith(("claude-", "anthropic-")):
        key = os.environ.get("ANTHROPIC_API_KEY")
        return ("anthropic", lambda t: claude_extract(model, key, t), "ANTHROPIC_API_KEY", key)
    if model.startswith(("gpt-", "o1-", "o3-", "chatgpt-")):
        key = os.environ.get("OPENAI_API_KEY")
        return ("openai", lambda t: openai_extract(model, key, t), "OPENAI_API_KEY", key)
    if model.startswith("gemini-"):
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return ("gemini", lambda t: gemini_extract(model, key, t),
                "GEMINI_API_KEY (or GOOGLE_API_KEY)", key)
    return ("ollama", lambda t: ollama_extract(model, t), None, "ollama-localhost")


def run_model(model: str, tweets, alias_map, canonicals_set,
              extractor):
    """Run both conditions on `tweets` using `extractor(text)` for LLM."""
    print(f"\n=== Model: {model} ===")
    print(f"  No proxy...")
    t0 = time.perf_counter()
    no_extracted = [extractor(tw["text"]) for tw in tweets]
    no_time = time.perf_counter() - t0

    print(f"  With proxy...")
    t0 = time.perf_counter()
    yes_extracted = [extractor(pre_normalize(tw["text"], alias_map))
                     for tw in tweets]
    yes_time = time.perf_counter() - t0

    n = len(tweets)
    no_correct = [
        1 if canonicalize_for_scoring(e, alias_map) == tw["oracle"] else 0
        for e, tw in zip(no_extracted, tweets)
    ]
    yes_correct = [
        1 if canonicalize_for_scoring(e, alias_map) == tw["oracle"] else 0
        for e, tw in zip(yes_extracted, tweets)
    ]
    no_canonical = [1 if e.strip() in canonicals_set else 0 for e in no_extracted]
    yes_canonical = [1 if e.strip() in canonicals_set else 0 for e in yes_extracted]

    no_acc = sum(no_correct) / n
    yes_acc = sum(yes_correct) / n
    no_canon = sum(no_canonical) / n
    yes_canon = sum(yes_canonical) / n

    diffs_acc = [y - x for y, x in zip(yes_correct, no_correct)]
    diffs_canon = [y - x for y, x in zip(yes_canonical, no_canonical)]
    res_acc = paired_bootstrap(diffs_acc, n_resamples=1000, seed=42)
    res_canon = paired_bootstrap(diffs_canon, n_resamples=1000, seed=43)

    no_unique = len(set(no_extracted))
    yes_unique = len(set(yes_extracted))

    print(f"  Accuracy:     {no_acc:.3f} -> {yes_acc:.3f}  "
          f"(Δ {res_acc.mean_diff:+.4f}, 95% CI [{res_acc.ci_low:+.4f}, "
          f"{res_acc.ci_high:+.4f}], p={res_acc.p_value_one_sided_gt:.4f})")
    print(f"  Canonical %:  {no_canon:.3f} -> {yes_canon:.3f}  "
          f"(Δ {res_canon.mean_diff:+.4f})")
    print(f"  Unique outputs: {no_unique} -> {yes_unique} "
          f"({100*(no_unique - yes_unique)/no_unique:+.1f}%)")
    print(f"  Time: no={no_time:.1f}s with={yes_time:.1f}s "
          f"({no_time*1000/n:.0f}ms vs {yes_time*1000/n:.0f}ms per call)")

    return {
        "model": model,
        "n_tweets": n,
        "accuracy_no_proxy": no_acc,
        "accuracy_with_proxy": yes_acc,
        "accuracy_diff": res_acc.mean_diff,
        "accuracy_ci_lo": res_acc.ci_low,
        "accuracy_ci_hi": res_acc.ci_high,
        "accuracy_p": res_acc.p_value_one_sided_gt,
        "canonical_rate_no_proxy": no_canon,
        "canonical_rate_with_proxy": yes_canon,
        "canonical_rate_diff": res_canon.mean_diff,
        "unique_outputs_no_proxy": no_unique,
        "unique_outputs_with_proxy": yes_unique,
        "time_no_proxy_s": no_time,
        "time_with_proxy_s": yes_time,
        "ms_per_call_no_proxy": no_time * 1000 / n,
        "ms_per_call_with_proxy": yes_time * 1000 / n,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ladder-sweep-real-data")
    parser.add_argument("--per-entity", type=int, default=30,
                        help="tweets per entity; default 30 for ~300 total to keep large-model runs tractable")
    parser.add_argument("--models", default=",".join(LOCAL_MODELS),
                        help="comma-separated list of Ollama models")
    parser.add_argument("--include-opus", action="store_true",
                        help="also run Claude Opus 4.7 via Anthropic API "
                        "(requires ANTHROPIC_API_KEY)")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "runs"
                        / f"ladder_sweep_real_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    args = parser.parse_args(argv)

    alias_map = build_alias_map()
    canonicals_set = set(alias_map.values())
    print(f"Alias map: {len(alias_map)} aliases / {len(canonicals_set)} entities")
    print(f"Loading Twitter Financial News validation, "
          f"filtering to {args.per_entity} per entity...")
    by_entity = load_filtered_tweets(args.per_entity, alias_map)
    tweets = []
    for canonical, tw_list in by_entity.items():
        for tw in tw_list:
            tw["oracle"] = canonical
            tweets.append(tw)
    print(f"Loaded {len(tweets)} tweets across {len(by_entity)} entities")

    models = args.models.split(",")
    all_results = []

    for model in models:
        provider, extractor, env_name, key = _route_extractor(model)
        if env_name is not None and not key:
            print(f"  SKIP {model}: {env_name} not set")
            all_results.append({"model": model, "provider": provider,
                                "error": f"{env_name}_not_set"})
            continue
        if provider != "ollama":
            print(f"\n[{provider}] {model} — making API calls")
        try:
            result = run_model(model, tweets, alias_map, canonicals_set,
                               extractor=extractor)
            result["provider"] = provider
            all_results.append(result)
        except Exception as e:
            print(f"  SKIP {model}: {type(e).__name__}: {e}")
            all_results.append({"model": model, "provider": provider,
                                "error": str(e)})

    if args.include_opus and OPUS_MODEL not in models:
        provider, extractor, env_name, key = _route_extractor(OPUS_MODEL)
        if not key:
            print(f"\nERROR: --include-opus requested but {env_name} not set.")
            return 1
        print(f"\n=== Running {OPUS_MODEL} (Anthropic API) ===")
        result = run_model(OPUS_MODEL, tweets, alias_map, canonicals_set,
                           extractor=extractor)
        result["provider"] = provider
        all_results.append(result)

    # Print final ladder summary
    print("\n" + "=" * 80)
    print("LADDER SUMMARY — Real-data tweet bench across LLM sizes")
    print("=" * 80)
    print(f"  {'Model':18} {'no_acc':>8} {'yes_acc':>8} {'Δ_acc':>8} {'no_canon%':>10} "
          f"{'yes_canon%':>11} {'Δ_canon':>8}")
    for r in all_results:
        if "accuracy_no_proxy" not in r:
            err = r.get("error", "unknown")
            print(f"  {r['model']:18} SKIPPED ({err})")
            continue
        print(f"  {r['model']:18} {r['accuracy_no_proxy']:>8.3f} "
              f"{r['accuracy_with_proxy']:>8.3f} {r['accuracy_diff']:>+8.4f} "
              f"{r['canonical_rate_no_proxy']:>10.3f} {r['canonical_rate_with_proxy']:>11.3f} "
              f"{r['canonical_rate_diff']:>+8.4f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_tweets": len(tweets),
        "results": all_results,
    }, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
