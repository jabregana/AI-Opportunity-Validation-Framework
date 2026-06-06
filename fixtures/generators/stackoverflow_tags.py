"""Build a multi-tenant workload from Stack Overflow related-tag data.

Approach: pick a set of programming language tags as "sources." For
each language, fetch related tags from the Stack Exchange API. A
"related tag" that appears under multiple language sources is a
cross-source entity that the proxy should merge.

Each workload entry is:
  (source_id=language, input=related_tag_name, oracle_canonical=related_tag_name)

The oracle is the related-tag name itself, which is the canonical form
in the Stack Overflow ecosystem. Two language sources writing the same
related-tag name should merge to the same canonical. Cross-language
ambiguity is rare in this domain (libraries are mostly globally
unambiguous); this workload tests cross-source consensus on real data.

Usage:
  python -m fixtures.generators.stackoverflow_tags --sources python javascript java go ruby
"""
from __future__ import annotations
import argparse
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "stackoverflow_tags.json"
_API = "https://api.stackexchange.com/2.3"
_UA = "agent-memory-gaps/0.1 (abregana@gmail.com)"


def _api_get(path: str, params: dict) -> dict:
    url = f"{_API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept-Encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def fetch_related_tags(language_tag: str, pagesize: int = 30) -> list[str]:
    """Returns the top N related tags for a given language tag,
    sorted by activity."""
    data = _api_get(
        f"/tags/{language_tag}/related",
        {"site": "stackoverflow", "pagesize": pagesize, "order": "desc", "sort": "count"},
    )
    return [item["name"] for item in data.get("items", [])]


def fetch_tag_synonyms(language_tag: str, pagesize: int = 50) -> list[tuple[str, str]]:
    """Returns (from_tag, to_tag) synonyms for tags starting with the
    given language prefix. For e.g. python this captures js / nodejs
    style synonym maps where applicable."""
    try:
        data = _api_get(
            f"/tags/{language_tag}/synonyms",
            {"site": "stackoverflow", "pagesize": pagesize, "order": "desc", "sort": "applied"},
        )
        return [(item["from_tag"], item["to_tag"]) for item in data.get("items", [])]
    except Exception:
        return []


def build(language_sources: list[str], per_source_limit: int = 25) -> dict:
    enriched = []
    for lang in language_sources:
        print(f"  fetching related for {lang}...")
        try:
            related = fetch_related_tags(lang, pagesize=per_source_limit)
        except Exception as e:
            print(f"    failed: {e}")
            related = []
        synonyms = fetch_tag_synonyms(lang)
        enriched.append({
            "source": lang,
            "related_tags": related,
            "synonyms": synonyms,
        })
        time.sleep(0.2)  # be polite to the API

    return {
        "schema_version": "1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": _API,
        "language_sources": language_sources,
        "per_source_limit": per_source_limit,
        "by_source": enriched,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stackoverflow-tags")
    p.add_argument("--sources", nargs="+",
                   default=["python", "javascript", "java", "go", "ruby", "rust"])
    p.add_argument("--per-source-limit", type=int, default=25)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = p.parse_args(argv)

    print(f"Fetching related tags for {len(args.sources)} languages...")
    data = build(args.sources, per_source_limit=args.per_source_limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2))
    print(f"\nWrote {args.out}")
    total = sum(len(s["related_tags"]) for s in data["by_source"])
    print(f"Total related-tag entries: {total}")
    # Show cross-source overlap
    tag_to_sources: dict[str, list[str]] = {}
    for s in data["by_source"]:
        for tag in s["related_tags"]:
            tag_to_sources.setdefault(tag, []).append(s["source"])
    cross_source = [(tag, srcs) for tag, srcs in tag_to_sources.items() if len(srcs) > 1]
    print(f"Cross-source tags (appear under 2+ languages): {len(cross_source)}")
    for tag, srcs in sorted(cross_source, key=lambda x: -len(x[1]))[:10]:
        print(f"  {tag:30s} in {srcs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
