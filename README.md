# agent-memory-gaps

An evaluation harness for a deterministic schema-alignment proxy for agent memory graphs. The proxy itself is not yet built. This repo holds the workloads, statistical framework, and CI gates that any candidate proxy must pass before it is taken seriously.

## What problem this addresses

Agent memory frameworks (Mem0, Graphiti, Cognee, Neo4j Agent Memory) turn unstructured agent observations into property graphs. They all hit the same problem: the same underlying relationship gets written under multiple names. `WORKS_AT`, `EMPLOYED_BY`, and `JOB_AT` become three separate edge types pointing at the same conceptual relation. This fragmentation degrades retrieval and forces every downstream query to enumerate variations.

Mem0's stated design choice (per maintainer comment on [issue #4896](https://github.com/mem0ai/mem0/issues/4896), April 2026) is to handle this with an LLM in the extraction prompt rather than a deterministic write-path resolver. Mem0 also removed graph memory from the OSS distribution in v2.0.0 / v3.0.0. That leaves an opening for a proxy that sits in front of any property-graph backend (Neo4j, Memgraph, Kuzu), vector-matches incoming relation names against existing schema, and aliases near-duplicates before the write commits. No LLM in the hot path.

A 90-day scan of the surrounding landscape is in [docs/opportunity.md](docs/opportunity.md). It records why three adjacent niches (LSP-driven code memory, reasoning-memory event sourcing, real-time graph GC) were either already shipped, partially closed, or deferred.

## Status

Pre-alpha. The harness runs end to end. The variants currently shipped are two stubs:

- `b-raw-identity` writes every relation surface form as its own bucket. Establishes the no-proxy floor.
- `stub-random-bucket` hashes relation strings into a fixed bucket pool. Sanity check.

No real proxy is implemented yet. The harness exists first so that any candidate proxy can be compared against the same workloads, the same metrics, and the same statistical gates.

## What's in this repo

```
fixtures/
  manifest.json                  workload registry (1 live, 5 stubs)
  workloads/w_conceptnet_rel.py  131 relations across 34 oracle canonicals
runner/
  variants/                      proxy implementations under test
  metrics/                       alignment F1, paired bootstrap, McNemar
  fdr.py                         LORD++ online FDR ledger
  cuped.py                       CUPED variance reduction
  gates.py                       three CI/CD edge-case guardrails
  artifacts.py                   immutable run-artifact writer
  runner.py                      entrypoint
tests/                           35 unit tests
docs/
  opportunity.md                 wedge selection and competitive landscape
  experiments.md                 test plan and statistical framework
```

## Pilot run

```sh
python -m runner.runner \
  --variant stub-random-bucket \
  --baseline b-raw-identity \
  --workload W-CONCEPTNET-REL \
  --use-case UC-4.1 \
  --tier fast
```

Writes a JSON artifact under `runs/` in the three-block schema described in `docs/experiments.md` section 6.1. The pipeline decision for the two stub variants is `BLOCK_PR`. Both stubs produce degenerate clusterings, so the harness correctly refuses to merge.

## Tests

```sh
python -m pytest tests/
```

35 tests cover the harness, the LORD++ ledger math, the CUPED implementation, the three CI/CD gates, and the end-to-end pipeline.

## Statistical framework, in one paragraph

The harness uses an online FDR procedure (LORD++ at q=0.10) rather than vanilla Benjamini-Hochberg, so that sequential peeking during development does not inflate the type-I error rate. Each candidate proxy version is compared against the previous green commit using non-inferiority testing with a tightened margin (0.25 of MDE for nightly, 0.5 of MDE for fast PR gates). CUPED variance reduction lets the harness afford the tighter margin without quadrupling sample size. Three operational guardrails (INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap at high null proportion, 14-day cap on stale baselines) protect the gate from common automation failures. Full spec in [docs/experiments.md](docs/experiments.md).

## Why this exists before the proxy does

Picking a wedge in a moving competitive landscape is easy to get wrong. The opportunity scan and the harness are deliberate sequencing: first establish that the niche is real and unoccupied, then put the measurement infrastructure in place, then build the proxy. The first real candidate variant will land against the same gates as every later iteration, so progress (or regression) is unambiguous.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, after which that release converts automatically to Apache 2.0.
