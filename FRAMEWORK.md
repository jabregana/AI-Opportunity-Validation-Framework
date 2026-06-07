# A framework for evaluating AI/ML/LLM opportunities

The agent-memory-gaps repository is, at the deepest level, **a reusable framework for evaluating whether a given AI/ML/LLM opportunity is real**. The schema-alignment proxy is the first opportunity it was applied to. The framework would work equally well on the next.

This document explains the framework — what's in it, why it's structured the way it is, and what it produced.

## The motivating question

When a new AI/ML/LLM opportunity surfaces (a wedge against an incumbent, a new application class, a cost-optimization angle), the natural question is: **is it real?** The honest answer requires more than a demo. It requires:

1. Picking a defensible wedge (vs three other plausible ones)
2. Designing experiments that can falsify the claim, not just confirm it
3. Running on synthetic data first (cheap iteration, controlled noise)
4. Running on real data second (catches synthetic-bias overclaims)
5. Running on substantial real data third (catches small-N overclaims)
6. Running across the full model size ladder (catches model-specific quirks)
7. Documenting negative results as honestly as positive ones

Most AI evaluation skips most of these. The framework here was built to not skip them.

## The four-stage progression

This is the heart of the framework. Each stage catches errors the previous stage missed.

```
THEORETICAL  →  SYNTHETIC DATA  →  REAL DATA  →  SUBSTANTIAL REAL DATA
   ↓               ↓                ↓               ↓
landscape      pilot variants   small benchmarks  scaled benchmarks
scan +         on contrived     on actual         on production-shape
wedge pick     workloads        text              workloads
   ↓               ↓                ↓               ↓
"is there      "does the        "does the         "what's the actual
 a slot?"      mechanism        mechanism work    magnitude and
                work?"          on real text?"    ranking at scale?"
```

Each stage produces a finding doc that either confirms the next stage is worth running OR documents why the opportunity dies here. Findings are versioned, dated, and never silently revised — corrections get their own finding doc.

### Stage 1: Theoretical

Output: `docs/opportunity.md`, `docs/landscape.md`, `docs/niches.md`, `docs/verification.md`.

90-day landscape scan of incumbents (Mem0, Graphiti, Cognee, Neo4j Agent Memory, Memgraph). Identified 4 candidate wedges. Killed 3 after verification (already shipped or partially closed by incumbents). Picked Niche 4: deterministic schema-alignment proxy.

This stage costs ~1 day of focused research. It prevents months of work on a wedge that's already closed.

### Stage 2: Synthetic data

Output: variant iteration v0.1.0 through v0.3.1, plus the harness (LORD++ FDR, paired bootstrap, CUPED, CI gates).

Built controlled workloads (ConceptNet relation synonyms, WikiData property aliases) with known oracle clusters. Iterated 4 variant generations. Found:
- Token-overlap alone (v0.1.0) catches case/underscore variants but misses paraphrases
- Neural embedder alone (v0.2.0) catches paraphrases but fails false-merge gate
- Hybrid concat (v0.3.0) was the winner on ConceptNet but failed WikiData Tier B
- Structural filter (v0.3.1) was the first variant to pass both gates

This stage caught its own bugs (flawed bootstrap design that produced impossible CIs) and forced the "real data flipped the ranking" finding when WikiData was introduced.

### Stage 3: Real data (small N)

Output: `docs/finding-small-llm-quality.md`, `docs/finding-real-dataset.md`, `docs/finding-scale-tweet.md`, plus 14-model ladder sweep on N=227 tweets.

Built integrations with three memory frameworks (Mem0, Graphiti, Cognee). Ran 30-utterance and 10-conversation synthetic LLM extraction benchmarks across local 1B-32B models + Claude Opus 4.7. The pattern was strong: proxy lifts everyone, 3B local + proxy was beating frontier.

Then expanded to 227 real Twitter Financial News tweets. Pattern held. Cost analysis suggested 1000x savings vs frontier API at equal-or-better accuracy.

**At this point we were one finding doc away from a strong commercial pitch.** The framework's discipline made us run one more stage.

### Stage 4: Substantial real data

Output: `docs/finding-substantial-N-revision.md` (the honest correction).

Expanded the alias map to 125 entities, pulled 836 matching tweets, re-ran the ladder. The headline collapsed:
- Small local 3B models dropped 10-11 pp at scale
- Frontier models dropped only 5-6 pp at scale
- The new top of the ranking: free local 7B (qwen2.5vl:7b) **ties** gpt-4o at 0.773
- Six different local models cluster at 0.755-0.773 with proxy

The revised commercial claim is **"competitive with frontier at fraction of cost"** — defensible but more modest than "beats frontier."

**This is the framework's biggest win.** It forced a downward revision of the public claim before the claim hit a customer or investor. The data that revealed the overclaim is the same data that supports the revised, more durable claim.

## What's in the framework that can be reused on the next opportunity

| Component | What it does | Reusable for any opportunity? |
|---|---|---|
| **Harness** (`runner/`) | LORD++ online FDR, paired bootstrap, CUPED, CI gates, three-block artifact schema | Yes — drop-in for any A/B-style ML evaluation |
| **Variant ABC + factory pattern** (`runner/variants/`) | Inject any new mechanism behind a common interface | Yes — pattern, not the variants themselves |
| **Multi-model ladder runner** (`experiments/ladder_sweep_real_data.py`) | Auto-routes to Anthropic / OpenAI / Google / Ollama by model prefix | Yes — works for any LLM eval |
| **Bootstrap + CI gates** (`runner/metrics/stats.py`) | Paired diff bootstrap with one/two-sided p-values | Yes |
| **Findings culture** (`docs/finding-*.md`, 24 docs) | Every claim, including negative results, gets a doc | Yes — discipline, not code |
| **Integration shim pattern** (`runner/service/integrations/`) | Wrap any external system behind a common contract | Yes — three reference implementations (Mem0/Graphiti/Cognee) |
| **Statistical rigor checklist** (`docs/experiments.md`) | Pre-registered tests, non-inferiority margins, INCONCLUSIVE-is-FAIL | Yes |

The schema-alignment proxy variants themselves (the `embed-proxy-*` family) are domain-specific. Everything else is general infrastructure.

## What the framework found about the schema-alignment proxy specifically

The opportunity is **real but narrow**. After 4 stages of evaluation:

- **Real value:** The proxy adds +8-15pp accuracy lift on entity-extraction LLM workloads, with rock-solid statistical significance. Universal across 10+ model families.
- **Narrower than initially claimed:** "Beats frontier" was an artifact of small-N benchmarks. Real claim is "ties frontier at fraction of cost."
- **Commercial moat is in the data, not the code:** The proxy is 50 lines of regex. The vertical alias maps (financial, pharma, legal) are the defensible asset.
- **Best-fit domains:** financial chat, clinical NLP, B2B SaaS customer support (per-tenant memory deployments).
- **Confirmed out-of-scope:** general conversational memory (LongMemEval regression), co-reference resolution (LLMs do it internally), open-ended entity discovery beyond surface-form variation.

This is the honest read after applying the framework's full rigor. It's a useful infrastructure component for entity-heavy LLM pipelines, not a market-defining product.

## What the framework would catch on the next opportunity

If we applied the same framework to (say) a new wedge in agent reasoning or autonomous coding, the framework would:

1. **Force a landscape scan first** — kill the wedge if incumbents already cover it
2. **Make us iterate on synthetic data with statistical gates** — catch mechanism bugs before scaling
3. **Make us run on real data at small N** — catch the synthetic-vs-real ranking flips
4. **Make us run at substantial N before publishing** — catch small-N overclaims
5. **Make us run across the model size ladder** — catch model-family quirks
6. **Make us document negative results** — preserves credibility, signals discipline
7. **Produce a finding doc per phase** — auditable evidence chain

The cost of applying the framework to a new opportunity is roughly:
- 1-3 days: theoretical + landscape scan
- 1-2 weeks: build the synthetic harness + first variant
- 3-5 days: real-data small-N benchmark
- 2-5 days: substantial real-data benchmark + ladder sweep
- Ongoing: finding docs per result

**Total: 4-6 weeks per opportunity, ending in a defensible go/no-go decision backed by data.**

That's the value of the framework. The schema-alignment proxy was the first opportunity it was applied to. The framework outlived the headline claim, which is exactly what a good framework does.

## How to read this repository

- **If you're an engineer:** read `runner/` for the harness, `runner/variants/` for the variant pattern, `runner/service/integrations/` for integration shims.
- **If you're evaluating the opportunity:** start with `docs/finding-substantial-N-revision.md` (latest honest read) and `docs/finding-full-ladder-sweep.md` (initial broad sweep) and `GAPS-AND-LIMITATIONS.md` (what we explicitly haven't proven).
- **If you're evaluating the framework:** read this doc + `docs/experiments.md` (statistical spec) + `docs/finding-*.md` chronologically. The progression of findings IS the framework working.
- **If you're considering applying the framework to a new opportunity:** the harness and integration shim patterns drop in clean. The findings culture is the harder part — you have to commit to writing the negative-result docs.

## Project trajectory through the framework

```
2026-06-05  Theoretical + landscape scan
            ↓
2026-06-05  Statistical framework + harness
            ↓
2026-06-05/06  Synthetic + semi-synthetic (ConceptNet, WikiData)
               v0.1.0 → v0.3.1, false-merge gate, neural ceiling probe
            ↓
2026-06-06  Multi-tenant variants v0.4.0 → v0.5.3
            Mem0, Graphiti, Cognee integration shims
            ANN scaling (v0.5.5, v0.5.7)
            ↓
2026-06-06  First LLM-quality benchmarks (single-sentence + multi-turn)
            Small-N (30 utterances): proxy lifts 1B-Opus to 0.95
            ↓
2026-06-07  Real-data benchmarks (227 Twitter tweets)
            14-model ladder including 4 frontier providers
            Initial headline: "3B beats every frontier"
            ↓
2026-06-07  SUBSTANTIAL-N pressure test (836 tweets, 125 entities)
            Revised: "7B ties frontier at 1000x lower cost"
            Framework catches its own overclaim
            ↓
2026-06-07  This document — framework narrative reframe
```

The dates are real. The framework took about 48 hours of focused effort to apply end-to-end. Each stage produced concrete artifacts. The negative-result discipline at the end is what makes the project credible.

That's the work. The proxy is the first case study. The framework is the asset.
