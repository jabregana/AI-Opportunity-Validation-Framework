"""Re-run the LongMemEval-S clustering comparison with and without the
NER preprocessor in front of each variant.

The honest comparison shape is preprocessor-on-both. If NER changes the
result, it should change it for the baseline too; the relevant question
is whether the proxy still regresses vs baseline when both have the
same preprocessor.

For each of {b-raw-identity, embed-proxy-v0.3.1}:
  - Without preprocessing (the original finding's setup)
  - With RegexNERPreprocessor in front

We then report:
  - Per-variant B-cubed F1 in each setup
  - The pairwise delta vs b-raw in each setup
  - Whether NER preprocessing closes or widens the regression

Run:
  .venv/bin/python experiments/ner_longmemeval_compare.py
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

from fixtures import workloads
from runner.metrics import alignment
from runner.service.preprocessors import RegexNERPreprocessor
from runner.variants import build


def _apply_preprocessor(text: str, preprocessor, normalize) -> str:
    """Run NER over text, normalize each extracted span, splice back
    right-to-left so offsets stay valid as the string mutates.

    Returns the substituted text. If the preprocessor extracts no
    spans, returns the input unchanged.
    """
    if preprocessor is None:
        return text
    spans = preprocessor(text)
    if not spans:
        return text
    spans = sorted(spans, key=lambda s: -s[0])
    out = text
    for start, end, surface in spans:
        canonical = normalize(surface)
        out = out[:start] + canonical + out[end:]
    return out


def _run(variant_id: str, workload, preprocessor) -> tuple[float, int, int]:
    """Ingest the workload with optional NER preprocessing, then re-query
    and return (B-cubed F1, total spans extracted, total characters changed).
    """
    v = build(variant_id)
    spans_extracted = 0
    chars_changed = 0

    # First pass: ingest. The variant sees the preprocessed text.
    for e in workload:
        preprocessed = _apply_preprocessor(
            e.input,
            preprocessor,
            lambda s, _v=v, _ctx=e.source_id: _v.align_with_context(
                s, {"source_id": _ctx}
            ),
        )
        if preprocessor is not None:
            spans = preprocessor(e.input)
            spans_extracted += len(spans)
            chars_changed += sum(end - start for start, end, _ in spans)
        v.align_with_context(preprocessed, {"source_id": e.source_id})

    if hasattr(v, "consolidate"):
        v.consolidate()

    # Second pass: re-query so post-consolidation merges are visible.
    preds: list[tuple[str, str]] = []
    oracle: list[tuple[str, str]] = []
    for e in workload:
        preprocessed = _apply_preprocessor(
            e.input,
            preprocessor,
            lambda s, _v=v, _ctx=e.source_id: _v.align_with_context(
                s, {"source_id": _ctx}
            ),
        )
        canonical = v.align_with_context(
            preprocessed, {"source_id": e.source_id}
        )
        preds.append((e.input, canonical))
        oracle.append((e.input, e.oracle_canonical))

    bc = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
    return bc, spans_extracted, chars_changed


def main():
    print("Loading W-LONGMEMEVAL-S...")
    w = workloads.load("W-LONGMEMEVAL-S")
    n_entries = len(w)
    n_oracles = len(set(e.oracle_canonical for e in w))
    print(f"  {n_entries} entries across {n_oracles} oracle clusters")

    preprocessor = RegexNERPreprocessor(
        catch_title_case=True, catch_acronyms=True
    )

    results = []
    for variant_id in ["b-raw-identity", "embed-proxy-v0.3.1"]:
        for label, pre in [("no-ner", None), ("with-ner", preprocessor)]:
            print(f"\nRunning {variant_id} ({label})...")
            t = time.perf_counter()
            bc, spans, chars = _run(variant_id, w, pre)
            elapsed = time.perf_counter() - t
            print(f"  B-cubed F1 = {bc:.4f} ({elapsed:.1f}s, "
                  f"{spans} spans extracted, {chars} chars changed)")
            results.append({
                "variant": variant_id,
                "ner": label == "with-ner",
                "bcubed_f1": bc,
                "elapsed_s": elapsed,
                "spans_extracted": spans,
                "chars_changed": chars,
            })

    by_key = {(r["variant"], r["ner"]): r["bcubed_f1"] for r in results}
    baseline_no = by_key[("b-raw-identity", False)]
    baseline_yes = by_key[("b-raw-identity", True)]
    proxy_no = by_key[("embed-proxy-v0.3.1", False)]
    proxy_yes = by_key[("embed-proxy-v0.3.1", True)]

    print("\n" + "=" * 60)
    print("Summary (B-cubed F1, higher is better)")
    print("=" * 60)
    print(f"{'':22} {'no NER':>10} {'with NER':>10} {'Δ NER':>10}")
    print(f"{'b-raw-identity':22} {baseline_no:>10.4f} {baseline_yes:>10.4f} "
          f"{baseline_yes - baseline_no:>+10.4f}")
    print(f"{'embed-proxy-v0.3.1':22} {proxy_no:>10.4f} {proxy_yes:>10.4f} "
          f"{proxy_yes - proxy_no:>+10.4f}")
    print(f"{'Δ proxy vs baseline':22} {proxy_no - baseline_no:>+10.4f} "
          f"{proxy_yes - baseline_yes:>+10.4f}")

    if proxy_yes - baseline_yes > proxy_no - baseline_no:
        verdict = "NER NARROWS the regression"
    elif proxy_yes - baseline_yes < proxy_no - baseline_no:
        verdict = "NER WIDENS the regression"
    else:
        verdict = "NER has no effect on the regression"
    print(f"\nVerdict: {verdict}")

    out_path = (
        ROOT / "runs"
        / f"ner_longmemeval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "workload": "W-LONGMEMEVAL-S",
        "n_entries": n_entries,
        "n_oracles": n_oracles,
        "preprocessor": "RegexNERPreprocessor (title_case=True, acronyms=True)",
        "results": results,
        "verdict": verdict,
    }, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
