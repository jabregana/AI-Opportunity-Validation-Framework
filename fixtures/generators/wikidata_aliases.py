"""Fetch WikiData property aliases via the wbgetentities REST API.

Each WikiData property (P-id) has a canonical label and an arbitrary
number of English alt-labels (aliases). For W-WIKIDATA-100K we treat:
  - the canonical label as the oracle canonical
  - each alias as one input write paired with that canonical
  - the label itself also paired with itself (sanity write)

The SPARQL endpoint (WDQS) is the more natural source but is currently
under aggressive rate limiting during an active outage. wbgetentities
batches up to 50 entities per request and uses standard MediaWiki API
quotas, which are friendlier.

Result is a deterministic JSON file cached at fixtures/data/
wikidata_aliases.json. The loader in fixtures/workloads/w_wikidata_props.py
reads this file.

Usage:
  python -m fixtures.generators.wikidata_aliases --max-pid 1000
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
_BATCH_SIZE = 50  # wbgetentities maximum

_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "wikidata_aliases.json"


def _fetch_batch(prop_ids: list[str], user_agent: str) -> dict:
    """One wbgetentities call for a batch of P-ids."""
    params = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": "|".join(prop_ids),
            "props": "labels|aliases",
            "languages": "en",
            "format": "json",
        }
    )
    req = urllib.request.Request(
        f"{_API_ENDPOINT}?{params}",
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def fetch(
    max_pid: int = 1000,
    user_agent: str = "agent-memory-gaps/0.1 (research; abregana@gmail.com)",
    sleep_between_batches: float = 0.2,
) -> list[dict]:
    """Fetch properties P1..P{max_pid} in batches of 50."""
    pids = [f"P{i}" for i in range(1, max_pid + 1)]
    out: list[dict] = []
    for batch_start in range(0, len(pids), _BATCH_SIZE):
        batch = pids[batch_start : batch_start + _BATCH_SIZE]
        data = _fetch_batch(batch, user_agent)
        entities = data.get("entities", {})
        for pid, ent in entities.items():
            if ent.get("missing") is not None:
                continue
            labels = ent.get("labels", {})
            aliases = ent.get("aliases", {})
            en_label = labels.get("en", {}).get("value", "").strip()
            en_aliases_raw = aliases.get("en", [])
            en_aliases = [
                a["value"].strip() for a in en_aliases_raw if a.get("value", "").strip()
            ]
            if en_label and en_aliases:
                out.append({"id": pid, "label": en_label, "aliases": en_aliases})
        if sleep_between_batches > 0:
            time.sleep(sleep_between_batches)
    # Sort by P-id numeric for deterministic ordering
    out.sort(key=lambda p: int(p["id"][1:]))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wikidata-aliases")
    p.add_argument("--max-pid", type=int, default=1000,
                   help="fetch P1..P{max_pid} (in batches of 50)")
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = p.parse_args(argv)

    t0 = time.perf_counter()
    print(f"Fetching P1..P{args.max_pid} via wbgetentities (50/batch)...")
    properties = fetch(max_pid=args.max_pid)
    elapsed = time.perf_counter() - t0

    n_pairs = sum(1 + len(p["aliases"]) for p in properties)
    out = {
        "schema_version": "1",
        "source": "wikidata wbgetentities REST API",
        "endpoint": _API_ENDPOINT,
        "max_pid": args.max_pid,
        "n_properties": len(properties),
        "n_workload_pairs": n_pairs,
        "properties": properties,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(
        f"Wrote {args.out} in {elapsed:.1f}s — "
        f"{len(properties)} properties with aliases, {n_pairs} workload pairs"
    )
    if properties:
        # Show a few examples
        print("  examples:")
        for p in properties[:5]:
            print(f"    {p['id']:>6s}  {p['label']!r}  ({len(p['aliases'])} aliases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
