# A framework for evaluating AI/ML/LLM opportunities

This repo is at its core **a reusable framework for testing whether an AI/ML/LLM opportunity is real**. The schema-alignment proxy is the first opportunity I tested with it. The framework works the same way on the next one.

This doc explains what is in the framework, why it is structured this way, and what it produced.

## The question this framework answers

When a new AI/ML/LLM opportunity surfaces (a wedge against an incumbent, a new application class, a cost-optimization angle), the question is: **is it real?** Answering that honestly takes more than a demo. It takes:

1. Picking a defensible wedge instead of one already taken
2. Designing experiments that can falsify your claim, not just confirm it
3. Running on synthetic data first (cheap, controlled)
4. Running on real data second (catches synthetic-bias overclaims)
5. Running on substantial real data third (catches small-N overclaims)
6. Running across the full model size ladder (catches model-specific quirks)
7. Documenting negative results as honestly as positive ones

Most AI evaluation skips most of those. This framework does not.

## The four stages

This is the heart of the framework. Each stage catches errors the previous stage missed.

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

Each stage produces a finding doc. The finding doc either says "next stage is worth running" or "the opportunity dies here." Findings are versioned and dated. You never silently edit a published finding. If you need to correct one, you write a new finding doc.

### Stage 1: Theoretical

Output: `docs/opportunity.md` and any supporting landscape notes.

Spend a few days reading the incumbent space. Find every shipped solution that overlaps your wedge. Kill any wedge that an incumbent already shipped or will likely ship in the next quarter. Pick one with on-record evidence the incumbent will not build it.

For me: 90-day scan of agent memory tools (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph). 4 candidate wedges. 3 killed because the work was already done or in progress. Picked Niche 4 (schema alignment proxy) because the Mem0 maintainer publicly rejected that approach on issue #4896.

Cost: about 1 day of focused research. Saves you months of work on a closed wedge.

### Stage 2: Synthetic data

Output: pilot variants of your mechanism, the statistical harness (LORD++ FDR, paired bootstrap, CUPED, CI gates), and finding docs per iteration.

Build a controlled workload where you know the right answer. Iterate variants of your idea against statistical gates. Most of the work happens here.

For me: built ConceptNet relation synonyms and WikiData property aliases as controlled workloads. Iterated 4 variant generations:
- Token-overlap alone (v0.1.0) catches case and underscore variants but misses paraphrases
- Neural embedder alone (v0.2.0) catches paraphrases but fails the false-merge safety gate
- Hybrid concat (v0.3.0) won on ConceptNet but failed WikiData Tier B
- Structural filter on top (v0.3.1) was the first variant to pass both gates

This stage caught two important things. First, a bug in my own bootstrap design that produced impossible confidence intervals. I found it because the harness flagged the impossibility. Second, the real WikiData data flipped the ranking I had from synthetic ConceptNet. Without that flip I would have shipped the wrong variant.

### Stage 3: Real data, small N

Output: integration shims for the downstream systems (Mem0, Graphiti, Cognee), plus benchmarks run across the full model ladder on small but real samples.

Hook your variant up to a real downstream system. Run it on real text. Use a small sample first (200 to 300 items). Run it across many different LLMs from many providers.

For me: built integration shims for all three memory frameworks. Ran 30-utterance synthetic LLM benchmarks first, then 10-conversation multi-turn benchmarks, then 227 real Twitter Financial News tweets. Tested across 14 models from 5 providers (1B to 32B local + Anthropic Opus + OpenAI gpt-4o + Google Gemini Pro and Flash).

The pattern looked strong. The proxy lifted everyone. Local 3B with proxy was beating frontier APIs. Cost analysis suggested 1000x savings over frontier API at equal or better accuracy.

**I was one finding doc away from a strong commercial pitch.** The framework's discipline made me run one more stage.

### Stage 4: Substantial real data

Output: a scaled benchmark that 5x to 10x the previous N, with a more diverse entity set. Either confirms the stage 3 headline or corrects it. Plus a finding doc.

This stage is the most important. This is where small-benchmark overclaims die.

For me: expanded the alias map from 34 aliases over 10 entities to 416 aliases over 125 entities. Pulled 836 matching tweets from the same Twitter validation split. Re-ran the local 10-model ladder + gpt-4o.

The headline collapsed:
- Small local 3B models dropped 10 to 11 percentage points
- Frontier models dropped only 5 to 6 percentage points
- The new top of the ranking: free local 7B (qwen2.5vl:7b) **ties** gpt-4o at 0.773
- Six different local models cluster at 0.755 to 0.773 with proxy

The revised commercial claim is **"competitive with frontier at fraction of cost,"** not "beats frontier."

**This is the framework's biggest win.** It forced a downward revision of a public claim before that claim reached a customer or investor. The same data that revealed the overclaim also supports the revised, more durable claim.

## What you can reuse on your own opportunity

| Component | What it does | Reusable for any opportunity? |
|---|---|---|
| **Harness** (`runner/`) | LORD++ online FDR, paired bootstrap, CUPED, CI gates, three-block artifact schema | Yes. Drop-in for any A/B-style ML evaluation. |
| **Variant ABC + factory pattern** (`runner/variants/`) | Inject any new mechanism behind a common interface | Yes. The pattern is what carries, not the variants themselves. |
| **Multi-model ladder runner** (`experiments/ladder_sweep_real_data.py`) | Auto-routes to Anthropic, OpenAI, Google, or Ollama by model name prefix | Yes. Works for any LLM eval. |
| **Bootstrap + CI gates** (`runner/metrics/stats.py`) | Paired diff bootstrap with one and two-sided p-values | Yes. |
| **Findings culture** (`docs/finding-*.md`, 24 docs) | Every claim, including the negative ones, gets a dated doc | Yes. Discipline, not code. |
| **Integration shim pattern** (`runner/service/integrations/`) | Wrap any external system behind a common contract | Yes. I have three reference implementations (Mem0, Graphiti, Cognee). |
| **Statistical rigor spec** (`docs/experiments.md`) | Pre-registered tests, non-inferiority margins, INCONCLUSIVE-is-FAIL on fast tier | Yes. |

The proxy variants themselves (the `embed-proxy-*` family) are specific to this opportunity. Everything else is general infrastructure.

## The bigger framing: agent systems as statistical systems

The framework's narrowest claim is "a four-stage evaluation pipeline for one AI mechanism at a time." That claim is true and already proven on two opportunities (schema-alignment proxy, real-time graph GC).

The framework's larger claim is more interesting. **An agent system has six measurable dimensions, and this framework is the shape of a tool that treats all six as a statistical system instead of a demo.**

The six dimensions:

1. **Model**: which LLM (or local model) the agent calls, and which size tier
2. **Prompt**: system prompts, instructions, output-format contracts
3. **Tools**: which tools the agent can invoke and how it selects and arguments them
4. **Memory**: what the agent stores, how it canonicalizes, how it prunes
5. **Execution policy**: how the agent decides the next step (ReAct, plan-and-execute, reflection loops, multi-agent handoff)
6. **Recovery behavior**: what happens on tool failure, refusal, partial result, retry, fallback

Most AI evaluation today covers one dimension at a time and does so anecdotally. A demo. A single benchmark. A vibes check. The novelty here is not the four stages by themselves. It is the discipline of running the same statistical machinery across every dimension that defines an agent system.

### Current coverage

Honest read on where this framework sits today against the six-dimension claim:

| Dimension | Coverage | What proves it |
|---|---|---|
| **1. Model** | **Strong.** | `experiments/ladder_sweep_real_data.py` auto-routes Anthropic / OpenAI / Google / Ollama by prefix. 14 models from 5 providers exercised in the proxy case study. |
| **2. Prompt** | **Scaffolded.** | `runner/dimensions/prompt/` ships the `PromptVariant` ABC, the `b-default-prompt` baseline, and factory registry. No real variants yet. The variant abstraction also carries prompt implicitly today (different prompt = different variant). |
| **3. Tools** | **Stage 1 wedge picked.** | `runner/dimensions/tools/` ships the ABC + noop baseline; `docs/opportunity-tools.md` picks Wedge A (tool-set composition benchmark suite) after surveying 10 incumbents (Anthropic / OpenAI SDKs, MCP, LangChain, LangGraph, AutoGen, CrewAI, Guardrails AI, Inspect AI, routing tools). Stage 2 plan sketched, not yet committed. |
| **4. Memory** | **Strong.** | The schema-alignment proxy ran all four stages. The graph-GC opportunity has Stages 1, 2 (PASS), 3 (PASS), and 4 (ARCHITECTURAL-PASS) complete. Both case studies live under `dimensions/memory/canonicalization/` and `dimensions/memory/lifecycle/` (backward-compat shims at the old paths). The graph-GC opportunity also ships an integration-shim contract at `dimensions/memory/lifecycle/integrations/` for hooking the variant into any downstream framework (Graphiti / Mem0 / Cognee) via a 150-line adapter. |
| **5. Execution policy** | **Scaffolded.** | `runner/dimensions/policy/` ships the `PolicyVariant` ABC, `AgentStep` dataclass, `b-single-shot-policy` baseline, and factory registry. No real variants yet. |
| **6. Recovery behavior** | **Stage 2 baseline PASS.** | Full Stage 1 + Stage 2 cycle complete on a second non-memory dimension. Pilot variants `recovery-v0.1.0-retry-with-backoff` (+19.40pp completion lift) and `recovery-v0.1.1-fallback-chain` (+26.60pp lift) both pass all four UC-REC gates against `b-abort-on-failure` baseline at 0.90x cost-per-completion. See `docs/finding-recovery-stage2-baseline.md`. Stage 3 (real LLM tool-use traces + multi-model ladder + real cost model) is the next iteration. |

Scorecard: 2 strong (model + memory; memory at Stage 4 ARCH-PASS), 1 Stage 2 PASS (recovery), 1 Stage 1 wedge-picked (tools), 2 scaffolded with stubs (prompt + policy). Four of the six dimensions are now actively producing finding docs and benchmark numbers. The architecture is fully real, not aspirational.

### Why the framework's mechanisms generalize to the other dimensions

Adding the missing dimensions is mechanical, not architectural:

- **The four-stage progression** drops in unchanged. For each dimension: landscape scan, synthetic variants, real-data small-N, substantial-real-data.
- **The Variant ABC + factory pattern** has been proven twice now (schema alignment, graph GC). `PromptVariant`, `ToolVariant`, `PolicyVariant`, `RecoveryVariant` are the same shape with a different `should_X` decision.
- **The multi-model ladder** is already model-aware. It runs every prompt / tool / policy / recovery variant across the same ladder for free.
- **The paired-bootstrap + LORD++ FDR + CI gates** are statistical primitives that do not care which dimension you are testing.
- **The finding-doc culture** is process, not code. It carries over by writing it.

### Why this framing is directionally novel

Most agent-eval tools live in one of two boxes:
- **Trace observability** (LangSmith, Langfuse, Arize Phoenix). Records what happened, does not test variants against each other under statistical control.
- **Single-dimension benchmarks** (Pydantic Evals, Inspect AI, model-only leaderboards). Tests one axis at a time, usually one prompt against one prompt.

The combination this framework is built for, **the same statistical discipline applied across every dimension that defines an agent system**, does not exist as a single tool today. The schema-alignment proxy is one dimension's worth of evidence that the pattern works. The graph-GC pilot is the second. The other four dimensions are wedge-sized openings that this framework's bones are already shaped for.

That is the strategic frame. The framework's value is not "another eval harness." It is "the first shape of a tool that measures an agent system as a statistical system."

## What the framework found about the schema-alignment proxy

The opportunity is **real but narrow.** After 4 stages of testing:

- **Real value:** The proxy adds 8 to 15 percentage points of accuracy on entity-extraction LLM workloads, with rock-solid statistical significance. The lift holds across 10+ model families.
- **Narrower than first claimed:** "Beats frontier" was a small-N artifact. The real claim is "ties frontier at fraction of cost."
- **Moat is in the data, not the code:** The proxy itself is about 50 lines of regex. The vertical alias maps (financial, pharma, legal) are the defensible asset.
- **Good-fit domains:** financial chat, clinical NLP, B2B SaaS customer support (per-tenant memory deployments).
- **Out of scope:** general conversational memory (LongMemEval regression), coreference resolution (LLMs do it internally), open-ended entity discovery beyond surface-form variation.

This is the honest read after the full framework ran. The proxy is a useful infrastructure component for entity-heavy LLM pipelines. It is not a market-defining product.

## What the framework would do on the next opportunity

Pick a new wedge (agent reasoning verification, real-time graph GC, structured-output validation, anything). Apply the same four stages:

1. **Stage 1 (1-3 days):** landscape scan, kill closed wedges, pick one with on-record incumbent evidence
2. **Stage 2 (1-2 weeks):** build the variant abstraction, iterate against statistical gates, write finding docs
3. **Stage 3 (3-5 days):** real-data workload at small N, full multi-model ladder, pause before publishing
4. **Stage 4 (2-5 days):** scale the workload 5x to 10x with more diverse entities, confirm or correct the stage 3 headline

The framework will:
- Force you to kill the wedge if incumbents already cover it
- Make you iterate on synthetic data with statistical gates so mechanism bugs surface before scaling
- Make you run on real data at small N so synthetic-vs-real ranking flips surface
- Make you run at substantial N before publishing so small-N overclaims surface
- Make you run across the model size ladder so model-family quirks surface
- Make you document negative results so the project stays credible
- Produce a finding doc per stage, giving you an auditable evidence chain

**Total cost: 4 to 6 weeks per opportunity, ending in a defensible go/no-go decision backed by data.**

That is what the framework is worth. The schema-alignment proxy was the first opportunity I ran through it. The framework outlived the original headline claim. That is what a good framework does.

## How to read this repo

- **If you are an engineer:** read `runner/` for the harness, `runner/variants/` for the variant pattern, `runner/service/integrations/` for the three integration shims.
- **If you are evaluating the proxy opportunity:** start with `docs/finding-substantial-N-revision.md` (the latest honest read), then `docs/finding-full-ladder-sweep.md` (initial broad sweep), then `GAPS-AND-LIMITATIONS.md` (what I explicitly have not proven).
- **If you are evaluating the framework:** read this doc, then `docs/experiments.md` (statistical spec), then `docs/finding-*.md` in chronological order. The progression of findings IS the framework working.
- **If you want to apply the framework to a new opportunity:** the harness and integration shim patterns drop in clean. The findings culture is the harder part. You have to commit to writing the negative-result docs.

## Project trajectory through the framework

```
2026-06-05  Theoretical + landscape scan
            |
2026-06-05  Statistical framework + harness
            |
2026-06-05/06  Synthetic + semi-synthetic (ConceptNet, WikiData)
               v0.1.0 -> v0.3.1, false-merge gate, neural ceiling probe
            |
2026-06-06  Multi-tenant variants v0.4.0 -> v0.5.3
            Mem0, Graphiti, Cognee integration shims
            ANN scaling (v0.5.5, v0.5.7)
            |
2026-06-06  First LLM-quality benchmarks (single-sentence + multi-turn)
            Small-N (30 utterances): proxy lifts 1B-Opus to 0.95
            |
2026-06-07  Real-data benchmarks (227 Twitter tweets)
            14-model ladder including 4 frontier providers
            Initial headline: "3B beats every frontier"
            |
2026-06-07  SUBSTANTIAL-N pressure test (836 tweets, 125 entities)
            Revised: "7B ties frontier at 1000x lower cost"
            Framework catches its own overclaim
            |
2026-06-07  This doc: framework narrative reframe
```

The dates are real. The framework took about 48 hours of focused work to apply end-to-end. Each stage produced concrete artifacts. The negative-result discipline at the end is what makes the project credible.

That is the work. The proxy is the first case study. The framework is the asset.
