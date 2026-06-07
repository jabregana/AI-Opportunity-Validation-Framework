# ai-wedge-harness

**A process for testing whether an AI or ML opportunity is actually worth building.**

I started by looking at agent memory tools. That work surfaced one specific opportunity, an entity-normalization proxy. I built this framework to test that opportunity properly. The framework worked. It is now reusable for the next opportunity.

This README has five parts:

1. How this started: the agent memory competitive analysis
2. The process: how the framework works
3. What the process found about the entity-normalization proxy
4. How to use the proxy
5. How to use the framework on your own opportunity

---

## 1. How this started: an agent memory competitive analysis

I studied agent memory tools: Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph. They all share the same five problems:

1. Fragmented extraction (every chunk gets its own LLM call, the graph never converges)
2. Graph explosion (no pruning, retrieval drags in junk edges)
3. Schema rigidity vs. semantic drift (`WORKS_AT`, `EMPLOYED_BY`, `JOB_AT` all become separate things)
4. Cold extraction tax (every write pays a full LLM call)
5. No reasoning memory (graphs store facts but not the decisions that produced them)

You don't have to rebuild any of these tools to fix those problems. You can sit in front of them as middleware. That's seems the real opening.

I picked four candidate wedges and checked each one against what the incumbents already shipped:

| Wedge | What it would do | Already taken? |
|---|---|---|
| 1. LSP code memory graph | Fast deterministic memory graph for code, MCP to IDEs | **Yes.** `Jakedismo/codegraph-rust` (786 stars) already ships this exact pipeline. |
| 2. Reasoning memory in SQLite | Lightweight event-sourced agent decision log | **Mostly.** Neo4j Agent Memory shipped 8 PyPI releases in 83 days covering this. |
| 3. Real-time graph GC | Reference-counted middleware that prunes dead nodes | **Not yet,** but the operational definition is fuzzy. |
| 4. Schema alignment proxy | Vector-match relation writes and auto-alias them before they hit the graph | **Not yet, and the signal is strong.** Mem0 maintainer rejected this approach on the record (issue #4896, April 2026). |

**I picked Niche 4.** When the closest incumbent's maintainer says "we will not build this," that is the cleanest signal you can get for a wedge. The full reasoning had four parts:

**1. The problem is concrete and expensive.** When you feed text into Mem0, Graphiti, or Cognee, an LLM extracts entities and writes them to a graph. The same entity arrives under multiple surface forms over time. "AAPL" today, "Apple Inc" tomorrow, "Apple Computer" in an older email. Each variant creates a separate node. A query for "Apple Inc" misses the memories stored under "AAPL." The system you built to remember things forgets them inconsistently.

**2. The current fix is structurally bad.** All five incumbents handle this with an LLM call inside the write path. Per-call cost is $0.005 to $0.05 depending on the model. Per-call latency is 500 to 2000 ms. Output is non-deterministic, so two writes seconds apart can produce different canonicals. Audit and compliance teams cannot inspect why a specific canonical was chosen. The whole approach scales poorly: 1 million entity writes per month costs $5,000 to $50,000 just for the normalization LLM calls.

**3. A deterministic alternative is structurally better.** Sit in front of the memory framework. Match incoming surface forms against existing canonicals via a regex or embedding lookup. Substitute the canonical before the write hits the framework. Cost per call drops to roughly zero (microseconds of regex). Latency drops to about 30 ms p99. Output is deterministic and auditable. The integrator controls the alias rules, not the LLM.

**4. The strategic position is durable.** Mem0 maintainer kartik-mem0 publicly rejected this approach on issue #4896 (April 2026): "our v3 SDK handles contradictions by design through the extraction prompt and memory linking, not through an explicit UPDATE/conflict resolution code path." That is not a roadmap gap to be filled next quarter. That is a design philosophy difference. An alternative architecture cannot be trivially copied by Mem0 because Mem0 has publicly committed to the opposite design. The same logic applies to Graphiti, Cognee, and Neo4j Agent Memory, all of which use LLM-in-extraction. The wedge is wide (every memory framework user) and the incumbents cannot quickly close it.

The risk now: pick the right wedge, build a quick demo, run one benchmark, declare victory. The benchmark is secretly too small or too easy. You publish a claim that falls apart the first time a customer presses on it.

My response: **build the testing framework before building the proxy.** The first commit was the harness, not a proxy. That decision is why this repo became a reusable framework instead of a one-off code drop.

Full landscape scan: [`docs/opportunity.md`](docs/opportunity.md).

## 2. The process: how the framework works

The framework has four stages. Each stage tests the opportunity harder than the last. Each stage catches errors the previous one missed.

```
THEORETICAL  ->  SYNTHETIC DATA  ->  REAL DATA  ->  SUBSTANTIAL REAL DATA
   |               |                  |              |
landscape       pilot variants    small benchmarks   scaled benchmarks
scan +          on contrived      on real text       on production-shape
wedge pick      workloads                            workloads
   |               |                  |              |
"is there       "does the         "does it work     "what's the actual
 a slot?"        mechanism         on real text?"    magnitude and
                 work?"                              ranking at scale?"
```

### What you do at each stage

**Stage 1: Theoretical.** Read the landscape. Find the incumbents. Kill any wedge that is already taken or that the incumbents will likely close soon. Pick one with on-record evidence the incumbent will not build it.

**Stage 2: Synthetic data.** Build the simplest variant of your idea. Run it against a controlled workload where you know the right answer. Iterate. Use a real statistical harness so you catch your own bugs. Most of the work happens here.

**Stage 3: Real data, small N.** Hook up the variant to a real downstream system (in my case, the LLM extraction pipeline). Run it against real text. Use a small sample first. Run it against many different models. This is where synthetic-vs-real ranking flips show up.

**Stage 4: Substantial real data.** Scale the real-data benchmark up 5x to 10x. Use a more diverse workload. Re-run. Either confirm your stage 3 headline or correct it. This is the most important stage because this is where small-benchmark overclaims die.

### What you use at each stage

| Tool | What it does | Why you need it |
|---|---|---|
| Statistical harness | LORD++ online FDR control, paired bootstrap, CUPED variance reduction, non-inferiority testing, three CI guardrails | Sequential testing during dev does not inflate false positives. Small effects get measured honestly. |
| Multi-model ladder | One script that runs your benchmark across 14+ models from Anthropic, OpenAI, Google, and local Ollama. Auto-routes by model name prefix. | Catches model-family-specific quirks. Same workload, different models, you see what travels. |
| Integration shim pattern | Drop-in wrappers for Mem0 (sync client), Graphiti (async client), Cognee (async module). All three share one contract. | When you add a new downstream system, you write 50 lines of adapter, not 500. |
| Finding-doc culture | Every claim, including the negative ones, gets a dated `docs/finding-*.md` | Future-you can re-read what was tried and what failed. Negative results stay as visible as positive ones. |
| No silent revisions | When you find an overclaim, you write a correction doc. You do not edit the old claim. | Your track record of self-correction becomes its own credibility signal. |

### Why this matters

Running this framework on a new opportunity takes about 4 to 6 weeks. You finish with a clear answer: yes, worth building, or no, kill it. Both backed by real data.

Without the framework, you ship overclaims. Customers tear them apart. You retract publicly. The framework's job is to catch those overclaims before anyone outside sees them.

Full framework narrative and the reusable component inventory: [`FRAMEWORK.md`](FRAMEWORK.md).

## 3. What the process found about the entity-normalization proxy

I ran all four stages on Niche 4 (the schema-alignment proxy). Here is what each stage produced.

### Stage 1: wedge picked, defensible

Niche 4 was the only candidate where the incumbent had publicly said "we will not build this." Stage 1 output was a clean go.

### Stage 2: the harness caught my own bias

I built four versions of the proxy (v0.1.0 token-only, v0.2.0 neural, v0.3.0 hybrid, v0.3.1 hybrid plus structural filter). On synthetic ConceptNet data, v0.3.0 looked like the winner.

Then I added real WikiData property aliases. The ranking flipped. v0.2.0 won the main metric on real data but failed the false-merge safety gate at 100%. If I had only tested on synthetic data, I would have shipped the wrong variant.

The harness also caught a bug in its own statistical bootstrap. The bootstrap was producing impossible confidence intervals because of a duplicate-pair pathology in the metric. Caught during pilot, fixed before any claim was published.

Stage 2 output: v0.3.1 became the single-tenant GA candidate. I later extended to multi-tenant (v0.4.0 through v0.5.7), including an ANN index for scale.

### Stage 3: the small-N "3B beats frontier" headline

I built integration shims for Mem0, Graphiti, and Cognee. Then I ran a 14-model ladder (10 local + 4 frontier APIs) on 227 real Twitter Financial News tweets.

| Rank at N=227 | Model | With-proxy accuracy |
|---|---|---|
| 1 | qwen2.5:3b (free local 3B) | 0.872 |
| 2 | llama3.2:3b (free local 3B) | 0.855 |
| 3 | gpt-4o (OpenAI) | 0.828 |
| ... | ... | ... |
| 10 | claude-opus-4-7 (Anthropic) | 0.758 |

I published this as: **"free local 3B + proxy beats every frontier API."**

It was statistically significant (p < 0.0001). It was consistent across providers. And it was wrong at scale.

### Stage 4: substantial-N revision, the headline collapsed

I expanded the alias map from 34 aliases over 10 entities to **416 aliases over 125 entities**. I pulled **836 matching tweets** from the same Twitter validation split, instead of 227. Then I re-ran the local 10-model ladder + gpt-4o.

The numbers moved a lot.

| Model | Small N=227 | Substantial N=836 | Drop |
|---|---|---|---|
| qwen2.5:3b + proxy | 0.872 | **0.758** | -11.4 pp |
| llama3.2:3b + proxy | 0.855 | 0.758 | -9.7 pp |
| qwen2.5vl:7b + proxy | 0.819 | **0.773** | -4.6 pp |
| **gpt-4o + proxy** | **0.828** | **0.773** | **-5.5 pp** |

Smaller models drop more at scale (10 to 11 points) than frontier models (5 to 6 points). The reason: frontier models have wider world knowledge for long-tail entities like regional banks, ETFs, and abstract concepts like "Federal Reserve." My small benchmark was tail-biased to famous brands. It made the small models look better than they actually are.

The revised ranking at substantial N:

| Rank at N=836 | Model | Type | With-proxy accuracy | Latency per call |
|---|---|---|---|---|
| 1 (tie) | **qwen2.5vl:7b** | Local 7B (free) | **0.773** | 199 ms |
| 1 (tie) | **gpt-4o** | OpenAI frontier | **0.773** | 588 ms |
| 3 (tie) | llama3.2:3b, qwen2.5:3b, qwen2.5vl:32b | Local (free) | 0.758 | 121 to 651 ms |

A free local 7B model **ties** gpt-4o exactly at 0.773. Six local models cluster between 0.755 and 0.773. The proxy lifts everyone to a ceiling around 0.77 that the workload itself imposes.

**The correct commercial claim: competitive with frontier at roughly 1000x lower cost.** Not "beats frontier." Cost per million records: about $0 self-hosted, about $5,000 for gpt-4o, about $10,000 for Opus.

The framework catching its own overclaim before it shipped to a customer is the most credibility-bearing thing this project produced. Full revision: [`docs/finding-substantial-N-revision.md`](docs/finding-substantial-N-revision.md).

### Honest read on where the proxy actually helps

| Where the proxy buys you something real | Where it does not |
|---|---|
| Financial news and trading alert routing | General conversational AI (the LLM does coreference on its own, I proved this) |
| Drug name normalization in clinical NLP | Long-form text understanding (LongMemEval regression) |
| Per-tenant memory for AI assistants on Mem0, Graphiti, or Cognee | Open-ended entity discovery beyond surface-form variation |
| CRM auto-tagging from emails and calls | Situations where you already run heavyweight ER tools like Senzing or Tilores |
| Internal knowledge search | One-off extraction jobs (setup cost greater than value) |

The proxy code is about 50 lines of regex plus an alias map. **It is not a moat on its own.** Anyone can rewrite it in a day.

What is defensible, in order of how much moat each gives you:
1. Curated vertical alias maps as a subscription. Pharma. Finance. Legal. This is the real moat.
2. Integration shim maintenance as the upstream APIs evolve.
3. The benchmark methodology and the reusable harness.
4. Brand and distribution: being known as "the entity normalization people."

This is plausibly a $1M to $10M ARR business if executed. It is not a $1B startup.

## 4. How to use the proxy

Three integration patterns:

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
# Pattern 2: drop-in middleware for Mem0
from mem0 import Memory
from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized

norm = EntityNormalizer("embed-proxy-v0.3.1")
m = Mem0PreNormalized(Memory(), norm, mention_map={"AAPL": "Apple Inc", "MSFT": "Microsoft"})
m.add("Bought AAPL today", user_id="trader1")
```

```python
# Pattern 3: drop-in middleware for Graphiti
from graphiti_core import Graphiti
from runner.service.integrations import GraphitiPreNormalized

g = GraphitiPreNormalized(Graphiti(...), norm, mention_map={...})
await g.add_episode(name="ep-1", episode_body="...", group_id="tenant_a")
```

Cognee has `CogneePreNormalized` for its async module-level API. All three wrappers share the same contract, so a new framework needs about 50 lines of adapter code.

Pick a variant by use case:

| Variant | Use it when |
|---|---|
| `embed-proxy-v0.3.1` | Single-tenant, you want the GA-tested option |
| `embed-proxy-v0.5.3-singleton-aware` | Multi-tenant, you need cross-source consolidation |
| `embed-proxy-v0.5.5-ann` | Single-tenant at production scale (K > 10k canonicals) |
| `embed-proxy-v0.5.7-mt-ann` | Multi-tenant at production scale |

## 5. How to use the framework on your own opportunity

What you can lift directly:

| Component | Where it lives | What it does |
|---|---|---|
| Harness | `runner/runner.py`, `runner/fdr.py`, `runner/cuped.py`, `runner/gates.py` | LORD++ FDR ledger, CUPED variance reduction, three CI guardrails |
| Statistical helpers | `runner/metrics/stats.py` | Paired bootstrap with one and two-sided p-values |
| Multi-model ladder | `experiments/ladder_sweep_real_data.py` | Auto-routes to Anthropic, OpenAI, Google, or Ollama by model prefix |
| Integration shim pattern | `runner/service/integrations/{mem0,graphiti,cognee}.py` | Three reference implementations for three downstream API shapes |
| Variant ABC + factory | `runner/variants/base.py`, `runner/variants/__init__.py` | Drop your new mechanism behind a common interface |
| Finding-doc structure | `docs/finding-*.md` (24 examples) | Not code, but the structure to copy |

How to run it on a new opportunity:

1. **Stage 1, about 1 to 3 days.** Do a landscape scan. Kill any wedge that an incumbent has already shipped or will ship soon. Pick one with on-record evidence the incumbent will not build it. Write a `docs/opportunity.md`-style doc.
2. **Stage 2, about 1 to 2 weeks.** Add your variant behind the variant interface. Build a synthetic workload where you know the right answer. Iterate variants against the statistical gates. Write a finding doc for every iteration.
3. **Stage 3, about 3 to 5 days.** Add a real-data workload. Build an integration shim for the downstream system. Run the multi-model ladder. Write a finding doc but do not publish the headline yet.
4. **Stage 4, about 2 to 5 days.** Scale the real-data workload 5x to 10x. Use a more diverse entity set. Re-run. Either confirm or correct the stage 3 headline. Publish only after this.

Total: 4 to 6 weeks per opportunity. You finish with a clear go or no-go answer backed by data.

## What's in this repo

```
FRAMEWORK.md                   the framework meta-narrative
CASE-STUDY.md                  technical writeup on the proxy
GAPS-AND-LIMITATIONS.md        candid audit of what is and is not proven

fixtures/                      workloads + adversarial test sets (6 workloads, 4 Tier B fixtures)

runner/                        the harness + variants + service
  service/                     PUBLIC API for integrators
    normalizer.py              EntityNormalizer
    consolidator.py            AdvisoryConsolidator
    integrations/              Mem0PreNormalized, GraphitiPreNormalized, CogneePreNormalized
    preprocessors/             NER (regex, spaCy, transformers) + coref (LLM, fastcoref)
  variants/                    13 candidate variants (single-tenant + multi-tenant + ANN)
  metrics/                     pairwise F1, B-cubed F1, paired bootstrap, McNemar
  fdr.py, cuped.py, gates.py   LORD++ FDR, CUPED variance reduction, CI gates
  runner.py                    entrypoint with UC-4.1, UC-4.4, UC-4.6, UC-4.7 modes

experiments/                   standalone analysis scripts (12+ benchmarks)
  ladder_sweep_real_data.py    multi-provider ladder runner with auto-routing
  case_study_expanded.py       125-entity, 416-alias map at substantial N (the stage 4 bench)

tests/                         194 unit tests, all passing

docs/
  opportunity.md               90-day landscape scan + wedge selection (stage 1)
  experiments.md               full statistical framework spec
  finding-*.md                 24 finding docs (every claim, including negative results)
  finding-substantial-N-revision.md   the self-correction (the framework working on itself)
```

## Running things

```sh
# Test suite
.venv/bin/python -m pytest tests/

# Variant comparison (clustering quality, paired bootstrap vs baseline)
python -m runner.runner \
  --variant embed-proxy-v0.3.1 \
  --baseline embed-proxy-v0.3.0 \
  --workload W-WIKIDATA-PROPS \
  --use-case UC-4.1 \
  --tier fast

# The substantial-N case study (125 entities, 416 aliases, 836 real tweets)
.venv/bin/python experiments/case_study_expanded.py --per-entity 1000 \
  --models qwen2.5:3b,llama3.2:3b,qwen2.5vl:7b

# Full multi-provider ladder including frontier APIs
ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=... \
.venv/bin/python experiments/ladder_sweep_real_data.py --per-entity 30 \
  --models claude-opus-4-7,gpt-4o,gemini-2.5-pro
```

Outputs land in `runs/` as immutable JSON artifacts.

## Optional dependencies

```sh
pip install -e .[neural]            # model2vec for hybrid + multi-tenant variants
pip install -e .[ann]               # hnswlib + numpy for ANN scaling variant
pip install -e .[ner]               # spaCy NER preprocessor
pip install -e .[ner-transformers]  # HuggingFace transformers NER preprocessor
```

The core harness, baseline, and stub variants need only the standard library.

## Status

Active. **194 tests passing.** 24 documented findings. 13 variants registered (single-tenant, multi-tenant, ANN-backed). Three memory-framework integrations (Mem0, Graphiti, Cognee). One 125-entity financial alias map for the substantial-N case study. Four-stage evaluation progression complete on the schema-alignment proxy opportunity.

The framework is the durable asset. The proxy is the first case study tested through it.

## License

[Functional Source License v1.1](LICENSE) with an Apache 2.0 future grant (FSL-1.1-ALv2). Source-available. Free for internal use, non-commercial education, non-commercial research, and professional services on top of the Software. Commercial use that competes with the Software is restricted until the second anniversary of each release, after which that release converts automatically to Apache 2.0.
