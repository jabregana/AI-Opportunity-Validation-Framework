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
| **Statistical primitives** (`runner/metrics/stats.py`, `runner/fdr.py`, `runner/cuped.py`) | Paired bootstrap, LORD++ online FDR, CUPED variance reduction | Yes. Pure functions, no opportunity-specific assumptions. |
| **Artifact writer** (`runner/artifacts.py`) | Immutable three-block JSON artifacts under `runs/` | Yes. |
| **CI gate machinery** (`runner/gates.py`) | INCONCLUSIVE-is-FAIL gate, SAFFRON hot-swap recommendation, B-VPREV freshness checks | Yes. |
| **Dimension `Variant` ABC pattern** (`runner/dimensions/<dim>/base.py`) | Per-dimension contract: prompt has `render()`, GC has `should_collect()`, recovery has `step_recover()`. Each dimension owns its shape. | Yes. Pattern carries; specific variant classes do not. |
| **Per-dimension runner template** (see below) | Each dimension has its own runner (`runner/gc_runner.py`, `runner/prompt_runner.py`, etc.) that owns its workload load, its gate computation, its artifact emission | Yes. Copy + adapt to the new dimension. |
| **Integration shim pattern** (`runner/service/integrations/`, `runner/dimensions/memory/lifecycle/integrations/`) | Wrap any external system behind a common contract | Yes. Six reference implementations across two opportunities (Mem0 / Graphiti / Cognee for canonicalization + same three for lifecycle). |
| **Multi-model ladder runner** (`experiments/ladder_sweep_real_data.py`) | Auto-routes to Anthropic, OpenAI, Google, or Ollama by model name prefix | Yes. |
| **Findings culture** (`docs/finding-*.md`, 30+ docs) | Every claim, including the negative ones, gets a dated doc | Yes. Discipline, not code. |
| **Statistical rigor spec** (`docs/experiments.md`) | Pre-registered tests, non-inferiority margins, INCONCLUSIVE-is-FAIL on fast tier | Yes. |

What is NOT reusable: the actual variant implementations (`embed-proxy-*`, `gc-v0.1.*`, `prompt-v0.1.*`), the dimension-specific gate thresholds (UC-4.1 vs UC-GC-RETRIEVAL vs UC-PROMPT-2), and the canonicalization-specific `runner/canonicalization_runner.py` (~681 lines tied to clustering / B-cubed F1 / oracle labels). These are opportunity-specific by design.

### Per-dimension runner pattern

Each agent-system dimension has fundamentally different metric shapes (F1 vs completion rate vs latency vs token cost vs precision/recall), different gate definitions (UC-GC-1..5 + UC-GC-RETRIEVAL vs UC-PROMPT-1..4 vs UC-REC-1..4), and different workload types (Q&A pairs vs prompt templates vs tool-call traces vs failure-injection sequences). Forcing them through a single universal runner would push complexity into config parsing and obscure what each experiment actually does.

The pattern this framework uses instead: **one runner per dimension, each ~200-450 lines, owning its dimension's full pipeline.**

```
runner/canonicalization_runner.py  681 lines  (entity-normalization proxy: UC-4.1, UC-4.4, UC-4.6, UC-4.7)
runner/gc_runner.py                407 lines  (memory lifecycle: UC-GC-1..5 + UC-GC-RETRIEVAL)
runner/prompt_runner.py            234 lines  (prompt variants: UC-PROMPT-1..4)
runner/tool_runner.py              262 lines  (tool selection: UC-TOOL-1..4)
runner/policy_runner.py            217 lines  (execution policy: UC-POLICY-1..4)
runner/recovery_runner.py          447 lines  (recovery behavior: UC-REC-1..4)
runner/cross_dim_runner.py         252 lines  (joint experiments across all six)
```

Each runner imports the shared statistical primitives but defines its own gates, its own metric calculations, and its own workload load. Per-runner duplication is real and intentional: a generic gate function would be leakier than five focused ones.

**Recipe for adding a new opportunity in a new dimension:**

1. Create `runner/dimensions/<your_dim>/base.py` with a `Variant` ABC for your dimension's decision shape (e.g., `should_retry()`, `route_query()`, etc.)
2. Implement candidate variants alongside (e.g., `runner/dimensions/<your_dim>/v0_1_0.py`)
3. Build a workload type in `fixtures/workloads/w_<your_dim>.py`
4. Copy the closest-shape existing runner (`gc_runner.py` for state-mutating ops, `prompt_runner.py` for pure-function evaluation, `recovery_runner.py` for trace-based replay) into `runner/<your_dim>_runner.py`
5. Replace the dimension import, the workload import, the gate function, and the artifact-emission keys
6. Register the variant factory in `runner/dimensions/<your_dim>/__init__.py`
7. Write a `docs/finding-<your_opportunity>-stage1.md` and run

Total: typically 2-3 engineer-days for a new dimension, then 4-6 weeks for the four-stage progression.

**What this framework explicitly does NOT include** (and probably should not, as of 2026-06-08): an `ExperimentSpec`-style config-driven runner. A universal runner would unify dimensions that legitimately differ in metric shape; the indirection would obscure rather than reduce real complexity. If you find yourself copy-pasting the same boilerplate into three new per-dim runners, that's the moment to extract a base runner. Not before.

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
| **2. Prompt** | **Stage 2 baseline PASS.** | Pilot variants `prompt-v0.1.0-cot`, `prompt-v0.1.2-few-shot-1`, and `prompt-v0.1.4-cot-plus-structured` pass all 4 UC-PROMPT gates against `b-default-prompt` baseline. Best: cot-plus-structured (+10.50pp completion at 1.32x cost). `prompt-v0.1.3-few-shot-3` fails UC-PROMPT-2 (2.09x cost) and `prompt-v0.1.1-direct-structured` fails UC-PROMPT-1 (+2.5pp insufficient). See `docs/finding-prompt-stage2-baseline.md`. |
| **3. Tools** | **Stage 2 v0.1.2 revision (still PARTIAL-PASS).** | `tool-v0.1.2-intent-plus-helper` improves recall (83.92% to 89.82%) but still 0.18pp short of UC-TOOL-3, and trades precision down to 16% (UC-TOOL-2 now also fails). Cross-dim still negative (joint config 31% < baseline 37%). See `docs/finding-tools-v0.1.2-revision.md`. v0.1.3 should attempt embedding-based classifier; keyword mechanism appears to have a ~90% recall ceiling on this workload. |
| **4. Memory** | **Strong on flat-memory frameworks; v0.2.x design pending for graph-native.** | The schema-alignment proxy ran all four stages. The graph-GC opportunity has Stages 1, 2 (PASS), 3 (PASS), 4 (ARCHITECTURAL-PASS), and 5 complete on Mem0 (flat memory): 2000-input smoke shows 98.4% steady-state reduction; multi-seed (n=3) F1 preservation at n=50 is mean 83.8%, 95% CI [74.5%, 88.8%], passing the >= 80% UC-GC-RETRIEVAL gate in 2 of 3 seeds. End-to-end Graphiti testing surfaced that v0.1.x's `in_degree == 0` orphan-node check never triggers on edge-rich graphs (see `docs/finding-graphiti-f1-stage5.md`); the v0.2.x family with graph-topology rules is designed at `docs/opportunity-v0.2.x-graph-topology-gc.md` but unbuilt. The path between "Mem0 stage 5 validated" and "customer-validated in production" is one pilot deployment. |
| **5. Execution policy** | **Stage 2 baseline PARTIAL-PASS.** | `policy-v0.1.3-handoff` passes all 4 UC-POLICY gates (+19.25pp completion at 1.32x cost). The richer multi-step variants (react, plan-execute, reflect-loop) lift completion by +20-29pp but fail UC-POLICY-2 (cost) and UC-POLICY-4 (latency). `plan-execute` is conditional second pick for cost-tolerant deployments. See `docs/finding-policy-stage2-baseline.md`. Stage 3 should run across the multi-model ladder to produce the model x policy interaction table. |
| **6. Recovery behavior** | **Stage 3 ROBUST-PASS (sensitivity).** | Stages 1, 2, and 3-sensitivity all complete. Both pilot variants pass all four UC-REC gates across five probability tables (optimistic, pessimistic, small-model, large-model, hostile); the variant ranking `fallback-chain > retry > baseline` is stable across all tables. See `docs/finding-recovery-stage3-sensitivity.md`. Real-LLM-trace Stage 3 (replace simulation table with measured probabilities) is the next iteration. |

Scorecard: 2 strong (model + memory), 1 Stage 3 ROBUST-PASS (recovery), 3 Stage 2 baseline (prompt PASS + tools PARTIAL-PASS + policy PARTIAL-PASS). **All six dimensions have completed Stage 2 or later.** The framework's six-dimension claim is now fully realized as code + tests + finding docs + benchmark numbers across every dimension.

### Cross-dimension orchestration

The framework runs **cross-dimension experiments** that walk scenarios through one variant of each of three dimensions simultaneously and measure interaction effects. Four findings so far:

1. **Single-config experiment** (`experiments/cross_dim_stage2.py` -> `docs/finding-cross-dim-interaction.md`): combining the best individual-dimension variants produces a config 12pp WORSE than all-baselines because `tool-v0.1.1-intent-classified`'s 83% recall multiplies through every other dimension.

2. **Full-matrix experiment** (`experiments/cross_dim_full_matrix.py` -> `docs/finding-cross-dim-full-matrix.md`): 72 configs (6 prompt x 4 tools x 3 recovery). 75% lose vs baseline; top-10 ALL use baseline tools.

3. **Cost-weighted matrix with bootstrap CIs** (`experiments/cross_dim_cost_weighted.py` -> `docs/finding-cross-dim-cost-weighted.md`): same 72 configs, plus per-config cost tracking and 95% CIs. 6 of top-10 are statistically indistinguishable from #1; the recommendation refines to `cot-plus-structured + b-allow-all-tools + fallback-chain` (statistically tied with few-shot-3 and slightly cheaper).

4. **Real-LLM Stage 3 scaffold** (`experiments/cross_dim_real_llm_stage3.py` -> `docs/finding-cross-dim-real-llm-stage3-scaffold.md`): end-to-end driver that runs the recommended config against a pluggable LLM client. Stub client ships; real client (Anthropic / OpenAI / Ollama) is a documented wiring task pending API access.

**This is the value proposition of the six-dimension architecture made operationally concrete: cross-dim is a deployment-decision mechanism, not just an organizing convenience.** Single-dim Stage 2 findings would have recommended shipping a tools variant; the cross-dim matrix refused. The cost-weighted CIs further refine that decision to a specific variant trio with calibrated confidence intervals.

### Strategic positioning: from research framework to decision tool

An analyst review reshaped how this framework should be positioned. The framework excels at mechanism evaluation + statistical effect size. The earlier version of this section called out engineering-cost estimates and business-KPI overlays as gaps. **Both now exist:**

- **Engineering-cost fields per variant**: `runner/variant_costs.py` ships eng-week and lift-per-week estimates for every variant in the registry. The investment-prioritization tool (`experiments/investment_prioritization.py`) consumes these to produce ranked FUND-NOW / DEFER / DO-NOT-BUILD verdicts.
- **Business-KPI overlays per dimension**: seven `docs/business-kpi-mapping-*.md` files (canonicalization, lifecycle, model, policy, prompt, recovery, tools) each translate UC-gate metrics into the customer-visible KPI that pays for the variant (token spend, completion rate, p99 latency, eng-hours saved).
- **Synthesis plan**: `docs/synthesis-memory-lifecycle-management.md` connects the lifecycle work to a four-phase product roadmap with explicit completion status per phase.

What is STILL missing: a customer pilot that converts those estimates into measured business outcomes. The framework can produce defensible go/no-go decisions today; the conversion from "research asset" to "commercial product" requires one external team to run a recommended bundle in production for 30 days and report their actual storage savings, latency change, and any incidents. That gap is named explicitly in the README's "Honest gaps" section and in the synthesis plan's Phase 4.

Earlier strategic-positioning proposals (per-audience report templates, README/FRAMEWORK reframe) have been substantially executed. See [`docs/strategic-framing-decision-tool.md`](docs/strategic-framing-decision-tool.md) for the original framing.

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
            |
2026-06-08  Memory lifecycle (graph GC) opportunity productized:
              Mem0 adapter + Graphiti adapter + Cognee adapter
              (real code, not just shims). Cross-adapter
              consistency test, integration-shim ABC.
              Real-Mem0 smoke: 2000 inputs, 98.4% reduction.
              Real-Mem0 F1 single-seed: 81.6% (n=50) + 81.8% (n=200).
              UC-GC-RETRIEVAL gate added.
              Production runbook (docs/runbook-mem0-v0.1.8-deploy.md).
              CI regression gate (.github/workflows/ci.yml).
              README reframed around two opportunities (entity-norm
              + memory lifecycle) + their commercialization status.
            |
2026-06-09  Two more framework self-corrections + methodology codified:
              Graphiti F1 across 3 scenarios all returned 0% reduction;
              cornered the architectural finding that v0.1.x's
              in_degree==0 orphan rule never triggers on edge-rich
              graphs. v0.2.x design (7 layers, configurable per
              domain/model/setup) documented in
              docs/opportunity-v0.2.x-graph-topology-gc.md.
              Multi-seed re-run of Mem0 F1 (n=3 seeds) revealed
              14pp variance hidden by single-seed reporting; revised
              headline to mean 84%, 95% CI [75%, 89%], pass-2-of-3.
              docs/benchmark-methodology.md codified the standard
              that caught this on first application. The artifact
              schema standardized (runner/artifacts.py::
              emit_dimension_artifact). docs/RUNNER-RECIPE.md
              documents the per-dim runner pattern with a worked
              example. canonicalization_runner.py renamed (was
              runner.py, misleadingly generic).
```

The dates are real. The framework took about 96 hours of focused work to apply end-to-end across two opportunities. Each stage produced concrete artifacts. The negative-result discipline plus three documented self-corrections (Stage 3 -> Stage 4 ranking flip on entity-norm; Graphiti architectural assumption; Mem0 F1 single-seed variance) plus the productization at Stage 5 of the lifecycle opportunity is what makes the project credible.

That is the work. The proxy is the first case study. The memory lifecycle is the second, currently the more-commercializable on its Mem0 path. The framework is the asset.
