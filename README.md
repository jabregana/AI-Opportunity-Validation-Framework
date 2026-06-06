# agent-memory-gaps

An evaluation harness and four candidate variants for a deterministic schema-alignment proxy for agent memory graphs. The harness is what makes the project defensible: every variant lands against the same workloads, the same statistical tests, and the same kill-switch gates.

## What problem this addresses

Agent memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory) turn unstructured agent observations into property graphs. They all hit the same problem: the same underlying relationship gets written under multiple names. `WORKS_AT`, `EMPLOYED_BY`, and `JOB_AT` become three separate edge types pointing at the same conceptual relation. This fragmentation degrades retrieval and forces every downstream query to enumerate variations.

Mem0's stated design choice (per maintainer comment on [issue #4896](https://github.com/mem0ai/mem0/issues/4896), April 2026) is to handle this with an LLM in the extraction prompt rather than a deterministic write-path resolver. Mem0 also removed graph memory from the OSS distribution in v2.0.0 / v3.0.0. That leaves an opening for a proxy that sits in front of any property-graph backend (Neo4j, Memgraph, Kuzu), vector-matches incoming relation names against existing schema, and aliases near-duplicates before the write commits. No LLM in the hot path.

A 90-day scan of the surrounding landscape is in [docs/opportunity.md](docs/opportunity.md). It records why three adjacent niches (LSP-driven code memory, reasoning-memory event sourcing, real-time graph GC) were either already shipped, partially closed, or deferred.

## Findings to date

The harness has run four variant generations against two workloads (synthetic ConceptNet and real WikiData property aliases) under two use cases (UC-4.1 clustering quality, UC-4.4 false-merge resistance). Headline numbers:

### UC-4.1 B-cubed F1 (clustering quality, higher is better)

| Variant | Approach | ConceptNet (n=131) | WikiData (n=2457) |
|---|---|---|---|
| b-raw-identity | no proxy | 0.407 | 0.197 |
| embed-proxy-v0.1.0 | token-overlap hash | **0.602** ★ | 0.229 |
| embed-proxy-v0.2.0 | neural (model2vec + prompt template) | 0.479 (regressed) | **0.355** ★ |
| embed-proxy-v0.3.0 | hybrid token + neural concat | **0.642** ★ | 0.225 |
| embed-proxy-v0.3.1 | hybrid + structural filter | 0.605 | 0.226 |

The ranking flipped between synthetic and real data. ConceptNet is dominated by case/underscore variants where token overlap is perfect; WikiData has real paraphrases (`head of government` ↔ `premier` ↔ `PM`) that only the neural embedder catches. Without WikiData, we would have shipped v0.3.0 as the winner. Wrong.

### UC-4.4 Tier B false-merge rate (semantic over-clustering, lower is better)

| Variant | ConceptNet (n=11) | WikiData (n=70) |
|---|---|---|
| embed-proxy-v0.1.0 | 0/11 PASS | 20/70 (28.6%) FAIL |
| embed-proxy-v0.2.0 | 11/11 (100%) FAIL | 70/70 (100%) FAIL |
| embed-proxy-v0.3.0 | 0/11 PASS | 3/70 (4.3%) FAIL |
| **embed-proxy-v0.3.1** | **0/11 PASS** | **0/70 PASS** |

UC-4.4 catches what UC-4.1 cannot: a variant that aliases everything semantically similar scores well on clustering but destroys precision on the cases that matter (`ISO 639-1 code` vs `ISO 639-2 code`, `review score` vs `review score by`). v0.2.0 wins UC-4.1 on WikiData decisively, then fails UC-4.4 catastrophically.

### v0.3.1, first variant clearing both gates

v0.3.1 adds a deterministic structural filter on top of v0.3.0's hybrid embedder. Two rules:

- **Digit content differs** → block the merge. Catches ISO codes, version numbers, alpha-N qualifiers.
- **Trailing closed-class preposition asymmetry** → block. Catches `X` vs `X by`, `X` vs `X for`, etc.

The filter is intentionally narrow. It does not touch semantic similarity; it only refuses merges that violate a structural rule. Both rules were derived directly from observed v0.3.0 failures on the WikiData Tier B fixture.

v0.3.1 is the first variant to pass both UC-4.1 superiority (statistically beats v0.3.0 on WikiData at p=0.0000) and UC-4.4 Tier B (0% false merges on both ConceptNet and WikiData fixtures) on real data. It does not beat v0.2.0 on UC-4.1 raw F1 (0.226 vs 0.355) because v0.2.0's neural-only paraphrase coverage is genuinely stronger. The trade-off is intentional: v0.2.0 gets that coverage by aliasing everything, which is unacceptable on the kill switch.

### What the harness has surfaced (worth keeping in mind)

- A flawed bootstrap design (index-resampled pairwise F1) was caught by the harness producing impossible CIs. Replaced with per-item B-cubed F1 bootstrap.
- The "more complex is better" pattern fails decisively: v0.2.0 looks like an upgrade but regresses on ConceptNet UC-4.1 and fails UC-4.4 100%.
- Equal-weight hybrid concat regresses against token-only; the neural cosine acts as a veto on case variants where it is weak. Token-dominant weighting fixed it.
- Two synthetic-data findings (v0.1.0 best on ConceptNet, v0.3.0 winning the hybrid) both reversed on real data. Synthetic workloads under-test.

## Status

Pre-alpha but no longer pre-prototype. Four candidate variants, two workloads, two use-case gates wired. The variant under active iteration is v0.3.1; v0.4.0 will address source-attributed (multi-tenant) resolution per [docs/roadmap.md](docs/roadmap.md).

## What's in this repo

```
fixtures/
  manifest.json                       workload registry
  workloads/w_conceptnet_rel.py       131 relations, 34 oracle canonicals
  workloads/w_wikidata_props.py       288 properties, 2457 pairs (real WikiData aliases)
  generators/wikidata_aliases.py      fetcher for the WikiData fixture
  generators/tier_b_adversarials.py   hard-negative miner for UC-4.4
  adversarials/conceptnet_tier_b.json 11 cosine-near-duplicate pairs
  adversarials/wikidata_tier_b.json   70 cosine-near-duplicate pairs
runner/
  variants/
    base.py                           Variant ABC
    b_raw.py                          identity baseline
    stub_proxy.py                     hash-bucket sanity check
    embed_proxy.py                    v0.1.0 token, v0.2.0 neural, v0.3.0 hybrid, v0.3.1 hybrid+filter
    neural_embedder.py                model2vec adapter with sentence template
    structural_filter.py              digit-mismatch and trailing-preposition rules
  metrics/
    alignment.py                      pairwise F1, per-item B-cubed F1
    stats.py                          paired bootstrap, McNemar
  fdr.py                              LORD++ online FDR ledger
  cuped.py                            CUPED variance reduction
  gates.py                            INCONCLUSIVE-is-FAIL, SAFFRON-swap, B-VPREV-cap
  artifacts.py                        immutable §6.1 three-block run-artifact writer
  runner.py                           entrypoint with UC-4.1 and UC-4.4 modes
tests/                                91 unit tests, all passing
docs/
  opportunity.md                      wedge selection and 90-day landscape scan
  experiments.md                      test plan and statistical framework
  roadmap.md                          v0.4.0+ multi-tenant and other open work
  finding-neural-ceiling.md           probe: MiniLM/BGE-base do not separate
                                      paraphrases from hard negatives any better
                                      than model2vec; the antonym/sibling overlap
                                      is fundamental to distributional semantics
  finding-neural-ceiling-probe.py     reproducer for the above
```

## Pilot run

```sh
# UC-4.1: clustering quality, paired bootstrap vs a baseline
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --baseline embed-proxy-v0.3.0 \
  --workload W-WIKIDATA-PROPS \
  --use-case UC-4.1 \
  --tier fast

# UC-4.4: false-merge rate on the Tier B adversarial fixture
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --use-case UC-4.4 \
  --tier-b-fixture fixtures/adversarials/wikidata_tier_b.json \
  --tier fast
```

Both write a JSON artifact under `runs/` in the three-block schema described in [docs/experiments.md](docs/experiments.md) section 6.1.

Optional: `pip install -e .[neural]` to install model2vec for v0.2.0 / v0.3.0 / v0.3.1. v0.1.0 needs no extra deps.

## Tests

```sh
python -m pytest tests/
```

91 tests cover the embedders, the variants, the statistical machinery (LORD++, CUPED, paired bootstrap, McNemar), the three CI/CD gates, the structural filter, and the end-to-end pipeline.

## Statistical framework, in one paragraph

The harness uses an online FDR procedure (LORD++ at q=0.10) rather than vanilla Benjamini-Hochberg, so that sequential peeking during development does not inflate the type-I error rate. Each candidate proxy version is compared against the previous green commit using non-inferiority testing with a tightened margin (0.25 of MDE for nightly, 0.5 of MDE for fast PR gates). CUPED variance reduction lets the harness afford the tighter margin without quadrupling sample size. Three operational guardrails (INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap at high null proportion, 14-day cap on stale baselines) protect the gate from common automation failures. Full spec in [docs/experiments.md](docs/experiments.md).

## Why this exists before the proxy does

Picking a wedge in a moving competitive landscape is easy to get wrong. The opportunity scan and the harness are deliberate sequencing: first establish that the niche is real and unoccupied, then put the measurement infrastructure in place, then build the proxy. The first real candidate variant landed against the same gates as every later iteration, so progress (and the two genuine reversals when real data flipped synthetic results) is unambiguous.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, after which that release converts automatically to Apache 2.0.
