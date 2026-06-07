"""Fetch WikiData entities for hand-curated ambiguous surface forms.

Track 2 of the v0.4.1 evaluation data plan. The synthetic Track 1
workload (W-MULTITENANT-SYNTH) is fast to author but the oracle is the
author's belief. This Track 2 workload anchors the oracle in WikiData's
actual entity structure, which is the closest available "external
ground truth" for which entities a given surface form can refer to.

Architecture:

  CURATED        Hand-authored list of (surface, [(QID, domain)]).
                 QIDs validated via prior wbsearchentities probe.
  Fetch          For each QID, retrieve label + aliases (en) via the
                 wbgetentities REST API.
  Synthesize     For each (alias_or_label, domain) pair, emit one
                 workload entry where:
                   source_id = domain
                   input     = alias (or the canonical label itself)
                   oracle    = fetched canonical label

A WorkloadEntry like ("automotive", "Mustang", "Ford Mustang") means:
the automotive team writing "Mustang" should resolve to the canonical
"Ford Mustang". A separate WorkloadEntry like ("biology", "Mustang",
"mustang") tests that the biology team writing the same surface form
resolves to the wild horse.

Cached JSON at fixtures/data/wikidata_disambiguation.json. Loader at
fixtures/workloads/w_multitenant_wikidata.py.

Reproducing:
  .venv/bin/python -m fixtures.generators.wikidata_disambiguation
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


_API_ENDPOINT = "https://www.wikidata.org/w/api.php"
_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "wikidata_disambiguation.json"


# Hand-curated list. QIDs validated via wbsearchentities probe on
# 2026-06-06. Each surface has multiple genuine real-world meanings;
# the domain assignment maps each meaning to a plausible org team that
# would surface that meaning in writes.
CURATED = [
    # Validated via direct wbsearchentities probe on 2026-06-06.
    {"surface": "Mustang", "candidates": [
        {"qid": "Q183476", "domain": "automotive", "expected": "Ford Mustang"},
        {"qid": "Q211848", "domain": "biology", "expected": "mustang"},
        {"qid": "Q192075", "domain": "military", "expected": "North American P-51 Mustang"},
        {"qid": "Q221562", "domain": "fashion", "expected": "Mustang Holding"},
    ]},
    {"surface": "Beetle", "candidates": [
        {"qid": "Q22671", "domain": "biology", "expected": "beetles"},
        {"qid": "Q152946", "domain": "automotive", "expected": "Volkswagen Beetle"},
    ]},
    {"surface": "Polo", "candidates": [
        {"qid": "Q134211", "domain": "sports", "expected": "polo"},
        {"qid": "Q6101", "domain": "history", "expected": "Marco Polo"},
    ]},
    {"surface": "Tiger", "candidates": [
        {"qid": "Q19939", "domain": "biology", "expected": "tiger"},
        {"qid": "Q10993", "domain": "sports", "expected": "Tiger Woods"},
    ]},
    {"surface": "Oracle", "candidates": [
        {"qid": "Q19900", "domain": "tech_company", "expected": "Oracle Corporation"},
        {"qid": "Q185524", "domain": "tech_product", "expected": "Oracle Database"},
        {"qid": "Q217123", "domain": "mythology", "expected": "oracle"},
    ]},
    {"surface": "Falcon", "candidates": [
        {"qid": "Q43489", "domain": "biology", "expected": "falcon"},
        {"qid": "Q249091", "domain": "aerospace", "expected": "Falcon 9"},
    ]},
    {"surface": "Cobra", "candidates": [
        {"qid": "Q2303322", "domain": "biology", "expected": "cobra"},
        {"qid": "Q219629", "domain": "military", "expected": "Bell AH-1 Cobra"},
    ]},
    {"surface": "Apple", "candidates": [
        {"qid": "Q312", "domain": "tech_company", "expected": "Apple Inc."},
        {"qid": "Q89", "domain": "biology", "expected": "apple"},
        {"qid": "Q213710", "domain": "music", "expected": "Apple Records"},
    ]},
    {"surface": "Mercury", "candidates": [
        {"qid": "Q308", "domain": "astronomy", "expected": "Mercury"},
        {"qid": "Q1150", "domain": "mythology", "expected": "Mercury"},
    ]},
    # Single-candidate surfaces. No multi-tenant ambiguity in this
    # dataset but still valid single-source entries (a v0.4.1 variant
    # should resolve each of these to its one canonical regardless).
    {"surface": "Saturn", "candidates": [
        {"qid": "Q193", "domain": "astronomy", "expected": "Saturn"},
    ]},
    {"surface": "Amazon", "candidates": [
        {"qid": "Q3884", "domain": "geography", "expected": "Amazon"},
    ]},
    {"surface": "Java", "candidates": [
        {"qid": "Q251", "domain": "tech_product", "expected": "Java"},
    ]},
    {"surface": "Python", "candidates": [
        {"qid": "Q28865", "domain": "tech_product", "expected": "Python"},
    ]},
    {"surface": "Jaguar", "candidates": [
        {"qid": "Q30055", "domain": "automotive", "expected": "Jaguar Cars"},
    ]},
    {"surface": "Raspberry Pi", "candidates": [
        {"qid": "Q245", "domain": "tech_product", "expected": "Raspberry Pi"},
    ]},
]


def fetch_entity(qid: str, user_agent: str) -> dict | None:
    """Returns {label, aliases, raw_qid} or None if missing."""
    params = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "labels|aliases",
            "languages": "en",
            "format": "json",
        }
    )
    req = urllib.request.Request(
        f"{_API_ENDPOINT}?{params}",
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    ent = data.get("entities", {}).get(qid, {})
    if ent.get("missing") is not None:
        return None
    label = ent.get("labels", {}).get("en", {}).get("value", "").strip()
    aliases_raw = ent.get("aliases", {}).get("en", [])
    aliases = [a["value"].strip() for a in aliases_raw if a.get("value", "").strip()]
    if not label:
        return None
    return {"qid": qid, "label": label, "aliases": aliases}


def fetch_all(curated=None, sleep_between=0.2) -> list[dict]:
    """Fetch all candidates in the curated list. Returns an enriched
    list with actual labels and aliases attached."""
    if curated is None:
        curated = CURATED
    UA = "ai-wedge-harness/0.1 (research; abregana@gmail.com)"
    out = []
    for surface_entry in curated:
        surface = surface_entry["surface"]
        enriched_candidates = []
        for cand in surface_entry["candidates"]:
            qid = cand["qid"]
            data = fetch_entity(qid, UA)
            if data is None:
                print(
                    f"  WARNING: {qid} missing or no English label, skipping",
                    file=sys.stderr,
                )
                continue
            enriched_candidates.append({
                "qid": qid,
                "domain": cand["domain"],
                "expected_label": cand.get("expected", ""),
                "actual_label": data["label"],
                "aliases": data["aliases"],
            })
            time.sleep(sleep_between)
        if enriched_candidates:
            out.append({
                "surface": surface,
                "n_candidates": len(enriched_candidates),
                "candidates": enriched_candidates,
            })
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="wikidata-disambiguation")
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = p.parse_args(argv)

    print(f"Fetching {sum(len(s['candidates']) for s in CURATED)} candidates "
          f"across {len(CURATED)} surface forms...")
    t0 = time.perf_counter()
    enriched = fetch_all()
    elapsed = time.perf_counter() - t0

    n_pairs = sum(
        sum(1 + len(c["aliases"]) for c in s["candidates"])
        for s in enriched
    )
    out = {
        "schema_version": "1",
        "source": "wikidata wbgetentities REST API",
        "n_surfaces": len(enriched),
        "n_candidates": sum(len(s["candidates"]) for s in enriched),
        "n_workload_pairs": n_pairs,
        "surfaces": enriched,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(
        f"Wrote {args.out} in {elapsed:.1f}s — "
        f"{len(enriched)} surfaces, {out['n_candidates']} candidates, "
        f"{n_pairs} workload pairs"
    )
    print("  per-surface summary:")
    for s in enriched:
        domains = [c["domain"] for c in s["candidates"]]
        print(f"    {s['surface']:12s}  {len(s['candidates'])} candidates  domains: {domains}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
