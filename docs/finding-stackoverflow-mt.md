# Finding: All Variants Regress on Stack Overflow Multi-Tenant

Status: experimental, June 2026.
Reproduce: `fixtures/generators/stackoverflow_tags.py` + UC-4.1 pilot.

## Setup

Built a second real-data multi-tenant workload to complement W-MULTITENANT-WIKIDATA. Where the WikiData workload tests disambiguation (same surface, different meanings per source), Stack Overflow tests cross-source consensus (same surface, same meaning across sources).

W-STACKOVERFLOW-MT structure:
- 6 sources: programming languages (python, javascript, java, go, ruby, rust)
- 211 entries: each language's top related tags from the Stack Exchange API
- 145 oracle canonicals (most tags are unique to one language; 17 appear under 2+ languages)

The interesting test cases are the 17 cross-language tags (arrays, json, regex, etc.). A working multi-tenant variant should merge them across sources.

## Results

| Variant | B-cubed F1 | vs b-raw |
|---|---|---|
| b-raw-identity | 0.8576 | --- |
| embed-proxy-v0.3.1 | 0.8201 | -0.037 REGRESSION |
| embed-proxy-v0.4.0 per-source | 0.7291 | -0.128 REGRESSION |
| embed-proxy-v0.4.3 AND rule | 0.7291 | -0.128 REGRESSION |
| embed-proxy-v0.4.4 adaptive | 0.7291 | -0.128 REGRESSION |

**Every proxy variant regresses against b-raw with statistical significance (p=1.0000, BLOCK_PR).**

## Why

The workload is dominated by GLOBAL-STRATUM SINGLETONS:
- 145 oracle canonicals across 211 entries = mostly 1:1 mapping
- Only 17 tags appear under 2+ languages
- The clear win opportunity is small relative to the total

b-raw's strategy ("each unique input is its own canonical") scores 0.858 because:
- Each singleton entry is in a perfectly clean cluster of 1 (precision = 1, recall = 1)
- Same input across sources gets the same canonical via identity (e.g., "json" from python and "json" from javascript both map to canonical "json")
- This catches the 17 cross-source merges trivially while keeping the 128 singletons perfectly precise

The proxy variants regress because:
- **v0.3.1** (single-tenant): aliases token-similar inputs even when they're conceptually distinct. "string" and "strings" might merge wrongly across the 145 canonicals.
- **v0.4.0** (per-source isolation): source-prefixes everything. "json" from python and "json" from javascript become different canonicals even though they're the same concept. Loses all 17 cross-source merges.
- **v0.4.3** (AND rule + min_overlap=2): with mostly single-alias clusters, the min_overlap=2 requirement blocks all cross-source merges. Same regression as v0.4.0.
- **v0.4.4** (adaptive): the density check requires "strong" pairs (overlap >= 2). With single-alias clusters, overlap is never > 1. Density = 0. v0.4.4 stays in conservative mode and behaves like v0.4.3.

## What this exposes

The variants assume each (source, local) cluster will accumulate MULTIPLE aliases over time. On workloads where each surface form is a singleton per source, that assumption breaks. The cross-source consolidation logic has no signal to fire on. The default min_aliases=2 then prevents any merge from being considered.

This is a third real workload pattern the variants don't handle well, alongside:
- LongMemEval (long-form text): proxies over-cluster on surface similarity
- Stack Overflow MT (singleton-heavy multi-tenant): proxies under-cluster because aggressive signal is absent

The variants work well on workloads with MULTIPLE ALIASES PER (SOURCE, ENTITY) (W-WIKIDATA-PROPS for single-tenant, W-MULTITENANT-SYNTH for multi-tenant). Outside that distribution they regress against b-raw.

## Implication

Two bigger-picture lessons:

1. **The b-raw baseline is stronger than we credit it.** On many real distributions, "give each unique input its own canonical" is hard to beat. Identity-clustering exploits the fact that real data often has repeated identical surface forms across sources for the same entity. Embedding-based clustering only helps when the surface forms VARY.

2. **The variants need a different mode for singleton-heavy data.** A potential v0.5.x design: when the inner variant produces mostly singleton clusters, fall back to aggressive cross-source identity-matching (merge if exact-string match across sources). This would catch the SO cross-language tags without the Tier B failure mode that broader aggressive settings produce.

## Implication for the narrative

The wedge thesis claim needs further narrowing:

  Before: "schema-alignment proxy for entity and relation name normalization in property graphs"
  After:  "schema-alignment proxy for entity and relation name normalization in property graphs WHERE EACH ENTITY HAS MULTIPLE ALIAS SURFACE FORMS"

When the data already has surface-form identity across sources (the SO case), the proxy adds no value. The proxy's value proposition is **alias normalization**, not entity identification.

## Appendix: reproducer

```sh
# Generate the workload
python -m fixtures.generators.stackoverflow_tags \
  --sources python javascript java go ruby rust --per-source-limit 30

# Run pilots
for variant in b-raw-identity embed-proxy-v0.3.1 embed-proxy-v0.4.4-adaptive; do
  python -m runner.runner \
    --variant $variant --baseline b-raw-identity \
    --workload W-STACKOVERFLOW-MT --use-case UC-4.1 --tier fast \
    --bootstrap-resamples 500
done
```
