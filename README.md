# ai-wedge-harness

**A reusable framework for evaluating AI/ML/LLM opportunities, applied to a deterministic entity-normalization proxy as the first case study.**

*(Originally named `agent-memory-gaps`. Renamed after the four-stage evaluation reframed the project around the framework rather than the specific wedge it was first applied to.)*

This repository is two interlocking artifacts:

1. **An evaluation framework** for assessing whether a given AI/ML/LLM opportunity is real — a four-stage progression (theoretical landscape scan → synthetic data → real data → substantial real data), a statistical harness (LORD++ online FDR, paired bootstrap, CUPED variance reduction, CI gates), a multi-model ladder runner that auto-routes to Anthropic / OpenAI / Google / Ollama, and a finding-doc culture where every claim — including negative results — gets a dated doc. See [`FRAMEWORK.md`](FRAMEWORK.md) for the full framework narrative and reusable component inventory.

2. **The schema-alignment proxy** as the first opportunity tested through it. Drop-in middleware that canonicalizes entity surface forms before the LLM extraction call, so the downstream memory system stores consistent canonicals instead of fragmenting into one entry per alias. Integrations for Mem0, Graphiti, and Cognee shipped.

## Honest read after four stages of evaluation

The proxy is **incrementally useful for entity-heavy LLM pipelines, not a market-defining product.** Three findings the framework caught:

| Stage | Headline | Survived substantial-N test? |
|---|---|---|
| Stage 2 (synthetic) | Proxy lifts B-cubed F1 from ~0.40 to ~0.95 on small workloads | No — small benchmark was too easy |
| Stage 3 (real, small N=227) | Free local 3B + proxy beats every frontier API (0.872 vs 0.758-0.828) | No — tail-entity bias in 10-entity map |
| **Stage 4 (substantial real, N=836)** | **Free local 7B + proxy ties gpt-4o at 0.773 each, at ~1000x lower cost** | **Yes — this is the defensible claim** |

The framework catching its own overclaim in stage 4 is the project's most credibility-bearing artifact. See [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md) for the full correction.

## The substantial commercial story (after the revision)

At N=836 real Twitter Financial News tweets covering 125 entities and 416 aliases, the ranking by with-proxy accuracy:

| Rank | Model | Provider | With-proxy accuracy | Latency / call |
|---|---|---|---|---|
| 1= | **qwen2.5vl:7b** | Local (free) | **0.773** | 199 ms |
| 1= | **gpt-4o** | OpenAI ($) | **0.773** | 588 ms |
| 3= | llama3.2:3b, qwen2.5:3b, qwen2.5vl:32b | Local (free) | 0.758 | 121–651 ms |
| 6 | gemma2:9b | Local (free) | 0.757 | 240 ms |
| 7 | llama3.1:8b | Local (free) | 0.755 | 213 ms |
| 8 | qwen2.5:14b | Local (free) | 0.746 | 281 ms |

A free local 7B model EXACTLY ties gpt-4o. Six local models cluster at 0.755-0.773. The proxy lifts everyone to a workload-imposed ceiling around 0.77.

**Cost per million records:** ~$0 (self-hosted 7B) vs ~$5,000 (gpt-4o) vs ~$10,000 (Claude Opus at prior small-N test).

**Latency per call:** local 7B is 3-8× faster than frontier APIs (no cloud RTT).

The defensible commercial pitch is **"competitive with frontier at fraction of cost"** — not "beats frontier." Useful for high-volume entity-extraction pipelines where the 1000× cost differential matters more than ~1.5pp accuracy.

## Where the proxy actually buys you something real

| Scenario | Why proxy helps | Realistic value |
|---|---|---|
| Financial news/trading alert routing | Subscribers want alerts on "Tesla" — feed says "TSLA"/"$TSLA"/"Tesla Motors". Proxy normalizes for direct match | Mid: cleaner ops |
| Drug name normalization (clinical NLP) | LLM extracts "Lipitor" — system needs "atorvastatin". Orange Book alias map IS the value | High: safety + compliance; **moat is in the map, not the code** |
| CRM auto-tagging from emails/calls | Sales note says "spoke with Citi" — CRM wants Citigroup record | Mid: fewer manual corrections |
| Per-tenant memory for AI assistants (Mem0/Graphiti/Cognee) | Cross-session entity continuity — user's "Acme deal" today links to "Sarah at Acme" 3 weeks ago | Real but smaller than initial claim — shared-store Mem0 does some dedup itself |
| Internal knowledge search | Pre-normalize entity mentions for consistent search index | Low-mid: precision improvement |

## Where the proxy is NOT useful

- General conversational AI (LLM does co-reference internally — proven negative result)
- One-off extraction (setup cost > value if you do it a few times — just call frontier)
- Already running heavyweight entity resolution (Senzing/Tilores/Reltio at the data layer)
- Long-form text understanding (LongMemEval regression — proxy is for entity names, not paragraph clustering)
- Open-ended entity discovery (embedding fallback misses acronym-expansion pairs like AAPL ↔ Apple Inc)

## How to use the proxy

Three integration patterns covering different downstream framework shapes:

```python
# Pattern 1: as a service in your own pipeline
from runner.service import EntityNormalizer, AdvisoryConsolidator

norm = EntityNormalizer("embed-proxy-v0.3.1")          # single-tenant
canonical = norm.normalize("Apple Inc")
batch = norm.batch_normalize(["AAPL", "Apple Computer", "Apple Inc."])

# Multi-tenant variant with per-source disambiguation + lazy consolidation
norm = EntityNormalizer("embed-proxy-v0.5.3-singleton-aware")
canonical = norm.normalize("Apple", context={"source_id": "finance"})

# AdvisoryConsolidator schedules cross-source merges off the hot path
consolidator = AdvisoryConsolidator(norm, schedule_every_n_writes=1000)
if consolidator.schedule_required():
    consolidator.run()
```

```python
# Pattern 2: drop-in middleware for Mem0 (sync client; per-user via user_id)
from mem0 import Memory
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized

norm = EntityNormalizer("embed-proxy-v0.3.1")
m = Mem0PreNormalized(Memory(), norm, mention_map={"AAPL": "Apple Inc", "MSFT": "Microsoft"})
m.add("Bought AAPL today", user_id="trader1")
```

```python
# Pattern 3: drop-in middleware for Graphiti (async client; per-tenant via group_id)
from graphiti_core import Graphiti
from runner.service.integrations import GraphitiPreNormalized

g = GraphitiPreNormalized(Graphiti(...), norm, mention_map={...})
await g.add_episode(name="ep-1", episode_body="...", group_id="tenant_a")
```

Cognee has its own wrapper (`CogneePreNormalized`) covering its async module-level API. All three share the same `mention_map` / `mention_extractor` contract; new memory frameworks plug in with ~50 lines of adapter code following the reference implementations in `runner/service/integrations/`.

## The four-stage progression (the framework's heart)

```
THEORETICAL  →  SYNTHETIC DATA  →  REAL DATA  →  SUBSTANTIAL REAL DATA
   ↓               ↓                 ↓              ↓
landscape       pilot variants    small benchmarks   scaled benchmarks
scan +          on contrived      on actual text     on production-shape
wedge pick      workloads                            workloads
   ↓               ↓                 ↓              ↓
"is there       "does the         "does it work     "what's the actual
 a slot?"        mechanism         on real text?"    magnitude and
                 work?"                              ranking at scale?"
```

Each stage catches errors the previous missed. **Stage 4 caught stage 3's overclaim** (and stage 2's was caught by stage 3 already). The framework's discipline forces escalation from synthetic toward substantial real data before any competitive claim ships.

See [`FRAMEWORK.md`](FRAMEWORK.md) for the full meta-narrative, the reusable component inventory, and the trajectory through the framework on this opportunity.

## Statistical framework, in one paragraph

The harness uses LORD++ online FDR (Ramdas et al. 2017) at q=0.10 rather than vanilla Benjamini-Hochberg, so sequential peeking during development does not inflate type-I error rate. Each candidate variant is compared against the previous green commit using non-inferiority testing with margin δ tied to MDE per metric (0.25×MDE for nightly, 0.5×MDE for fast PR gates). CUPED variance reduction (using B-VPREV per-item baseline) offsets the resulting sample-size inflation. Three operational guardrails (INCONCLUSIVE-is-FAIL on the fast tier, SAFFRON hot-swap at high null proportion, 14-day cap on stale baselines) protect against common automation failures. Full spec in [`docs/experiments.md`](docs/experiments.md).

## What's in this repo

```
FRAMEWORK.md                   the framework meta-narrative (start here for the meta)
CASE-STUDY.md                  tight technical narrative on the proxy specifically
GAPS-AND-LIMITATIONS.md        candid audit of what is and isn't proven

fixtures/                      workloads + adversarial test sets
  workloads/                   ConceptNet, WikiData props, multi-tenant variants,
                               Stack Overflow tags, LongMemEval-S adapted
  adversarials/                Tier B hard-negative fixtures (single + cross-source)
  generators/                  fetchers for WikiData, Stack Overflow, Tier B mining

runner/                        the harness + variants + service
  service/                     PUBLIC API for integrators
    normalizer.py              EntityNormalizer (the stable contract)
    consolidator.py            AdvisoryConsolidator (off-hot-path merging)
    integrations/              Mem0PreNormalized, GraphitiPreNormalized, CogneePreNormalized
    preprocessors/             NER (regex/spaCy/transformers) + co-reference (LLM/fastcoref)
  variants/                    13 candidate variants (single-tenant + multi-tenant + ANN)
  metrics/                     pairwise F1, B-cubed F1, paired bootstrap, McNemar
  fdr.py, cuped.py, gates.py   LORD++ FDR, CUPED variance reduction, CI gates
  runner.py                    entrypoint with UC-4.1, UC-4.4, UC-4.6, UC-4.7 modes

experiments/                   standalone analysis scripts (8+ benchmarks)
  ladder_sweep_real_data.py    14-model ladder runner with auto-routing
  case_study_expanded.py       125-entity / 416-alias map at substantial N
  mem0_wrapper_live_bench.py   live Mem0 deployment comparison
  ...                          (small-LLM quality, conversational, multi-session,
                                NER, coref, scale stress, etc.)

tests/                         194 unit tests, all passing

docs/
  opportunity.md               90-day landscape scan + wedge selection (stage 1)
  experiments.md               full statistical framework spec
  finding-*.md                 24 finding docs (every claim, including negative results)
```

## Running the harness

```sh
# Test suite
.venv/bin/python -m pytest tests/

# A variant comparison (clustering quality, paired bootstrap vs baseline)
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --baseline embed-proxy-v0.3.0 \
  --workload W-WIKIDATA-PROPS \
  --use-case UC-4.1 \
  --tier fast

# The substantial-N case study (125 entities, 416 aliases, 836 real tweets)
.venv/bin/python experiments/case_study_expanded.py --per-entity 1000 \
  --models qwen2.5:3b,llama3.2:3b,qwen2.5vl:7b

# Full 14-model ladder including frontier APIs
ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... \
.venv/bin/python experiments/ladder_sweep_real_data.py --per-entity 30 \
  --models claude-opus-4-7,gpt-4o,gemini-2.5-pro
```

Outputs land in `runs/` as immutable JSON artifacts in the three-block schema described in [`docs/experiments.md`](docs/experiments.md) §6.1.

## Optional dependencies

```sh
pip install -e .[neural]          # model2vec for hybrid + multi-tenant variants
pip install -e .[ann]             # hnswlib + numpy for the ANN scaling variant
pip install -e .[ner]             # spaCy NER preprocessor
pip install -e .[ner-transformers] # HuggingFace transformers NER preprocessor
```

The core harness, baseline, and stub variants need only stdlib.

## Status

Active. **194 tests passing.** 24 documented findings. 13 variants registered (single-tenant + multi-tenant + ANN-backed). Three memory-framework integrations (Mem0, Graphiti, Cognee). One curated 125-entity financial alias map for the case study. Four-stage evaluation progression applied through stage 4.

GA candidates by use case:
- **Single-tenant entity normalization:** v0.3.1 (hybrid + structural filter)
- **Multi-tenant with cross-source consolidation:** v0.5.3 (singleton-aware lazy)
- **Production K-scaling:** v0.5.5-ann (single-tenant) or v0.5.7-mt-ann (multi-tenant)

See [`GAPS-AND-LIMITATIONS.md`](GAPS-AND-LIMITATIONS.md) for the candid view of what's still open work.

## Why this exists (and what it isn't)

**What this is:** A rigorous answer to "is the schema-alignment opportunity real?" — backed by 4 stages of evaluation, 194 tests, 24 finding docs, 14 models tested across 5 providers, and one published self-correction when the small benchmark turned out to be misleading. Also: a reusable framework that could be re-applied to the next AI/ML/LLM opportunity in ~4-6 weeks.

**What this isn't:** A $1B startup. The proxy code is ~50 lines of regex with an alias map; any competent engineer can reproduce it in a day. The defensible commercial assets (if any) are the vertical alias maps (data subscription business), the integration shim maintenance, and the brand/distribution of being the entity-normalization-people. Treat this repo as a portfolio piece + reference architecture, not as a product roadmap.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, after which that release converts automatically to Apache 2.0.
