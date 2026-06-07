# Roadmap

What's planned next, ranked by leverage. The previous roadmap (the multi-tenant track before v0.4.0 shipped) is fully done. This version reflects what is actually next as of June 2026, after the substantial-N revision.

## Context

The project has completed all four evaluation stages on the schema-alignment proxy opportunity. Honest conclusion: incrementally useful for entity-heavy LLM pipelines, real but narrow, not market-defining. The framework that produced this conclusion is the durable asset.

Two paths from here:

- **Path A.** Continue investing in the proxy as a commercial product. Build vertical alias maps, run live customer pilots, ship a memory-auditor tool.
- **Path B.** Apply the framework to the next AI/ML/LLM opportunity. The four-stage progression, the harness, the multi-model ladder, the integration shim pattern, and the finding-doc culture all carry forward.

The roadmap covers both.

## Immediate next steps (1-2 weeks)

### 1. Complete the substantial-N ladder (Path A, low cost, high signal)
**Why.** The substantial-N revision tested 10 local + gpt-4o. Opus and Gemini Pro/Flash have not been re-run at N=836 yet. Completing them locks in the revised ranking across all four frontier providers.
**Cost.** About $50 in API + 30 min runtime.
**Output.** Final 14-model substantial-N ranking. Pins the "7B ties frontier at fraction of cost" headline across all providers.

### 2. Cache-warmed Mem0 latency A/B (Path A, low cost)
**Why.** The current Mem0 latency comparison was confounded by cold vs warm Ollama cache. The actual per-call overhead of the wrapper is about 0 ms but is not measured cleanly.
**Cost.** 30 min to re-run with explicit cache warming.
**Output.** A clean overhead number for the integration docs.

### 3. Multi-corpus generalization test (Path A, medium cost)
**Why.** The substantial-N result is on Twitter Financial News only. A second corpus (Reuters financial news, Reddit r/wallstreetbets) tests whether the pattern is corpus-specific.
**Cost.** A few hours to integrate a second dataset, plus about $50 in API for cross-model comparison.
**Output.** A multi-corpus version of `docs/finding-substantial-N-revision.md`.

## Medium-term (1-2 months)

### 4. Pharma vertical case study (Path A, real commercial signal)
**Why.** The financial case study (50-entity map, then 125-entity map, then 836 tweets) demonstrated the pattern in finance. Pharma is the next-highest-value vertical (regulated, large LLM bills at incumbents). Brand-generic drug normalization plus FDA Orange Book aliases.
**Cost.** About 1 week to curate a 200-entity pharma alias map. A few days to find an appropriate clinical NLP corpus (PubMed abstracts, MIMIC-III with proper access). A few hours of benchmark runs.
**Output.** `experiments/case_study_pharma.py` plus `docs/finding-case-study-pharma.md`. Demonstrates that the pattern transfers across verticals. Becomes the second buyer-facing case study.

### 5. Memory store auditor tool (Path A, land-and-expand)
**Why.** A diagnostic-led GTM. A free tool that scans an existing Mem0, Graphiti, or Cognee store, reports fragmentation per entity, and suggests alias-map additions. Easier conversation starter than "subscribe to our wrapper."
**Cost.** About 1 to 2 weeks to build. Read from each integration's store API, run NER and an embedder over stored memories, output a fragmentation report.
**Output.** An `auditor/` package. CLI: `amg-audit --backend mem0 --user trader1`. Generates an HTML report.

### 6. Apply the framework to a second AI/ML opportunity (Path B, the meta-value)
**Why.** The framework's durability is unproven until it is applied to a second opportunity. Candidates:
- **Agent reasoning verification.** Trace-based audit of multi-step agent decisions. Niche 2 from the original landscape scan, now partially closed by Neo4j Agent Memory but still has form-factor angles.
- **Real-time graph GC.** Niche 3 from the original scan, still open per the original verification.
- **A new opportunity not yet scoped.** Structured-output validation, prompt-injection defenses, multi-modal entity normalization, anything you want.

**Cost.** 4 to 6 weeks per opportunity for a complete four-stage evaluation.
**Output.** A second case study applying the same framework. Two case studies establish a pattern.

## Long-term (3+ months)

### 7. Live customer deployment (Path A)
**Why.** All current claims rest on lab benchmarks. A live deployment with a real customer (fintech, pharma, support automation) is what turns the project from "rigorous prototype" into "production-validated middleware."
**Cost.** Months of customer development, contract work, integration support.
**Output.** A customer logo plus a case study with a real cost-savings number from production.

### 8. Vertical alias map subscription business (Path A, the real moat)
**Why.** The proxy code is about 50 lines and not defensible. The vertical alias maps ARE the moat. Financial (500+ entities), pharma (10k+ drugs), legal citations, B2B SaaS customer normalization. Subscription delivery plus quarterly updates.
**Cost.** Ongoing curation. Requires domain expertise per vertical.
**Output.** Recurring revenue. Plausibly $1M to $10M ARR at scale across multiple verticals.

### 9. Open-source community + brand (Path A, distribution moat)
**Why.** The Datadog and Sentry playbook. Give the engine away, sell the data and the service. Requires sustained community investment (PRs, conference talks, content marketing).
**Cost.** Multi-year. Probably needs a dedicated DevRel person.
**Output.** Brand recognition as "the entity normalization people" for AI engineers.

## Items from the original roadmap that are now done

For reference, the original roadmap planned the multi-tenant track that has since fully shipped:

- v0.4.0 source-attributed resolution. Multi-tenant per-source isolation.
- v0.4.1 cross-source consensus via Jaccard.
- v0.4.2 lazy consensus (production-shape design).
- v0.4.3 AND-rule safety.
- v0.4.4 adaptive introspection.
- v0.5.0 bug fixes from multi-tenant Tier B.
- v0.5.1 EntityNormalizer service API.
- v0.5.2 Mem0PreNormalized wrapper.
- v0.5.3 singleton-aware variant.
- v0.5.4 README + CASE-STUDY middleware reframe.
- v0.5.5 ANN index (28x single-tenant speedup).
- v0.5.6 NER preprocessor (with negative result on LongMemEval).
- v0.5.7 multi-tenant ANN (6.88x speedup).
- v0.6.0 Graphiti and Cognee integration shims.

Plus the 24 finding docs, 8+ standalone experiment scripts, the framework reframe, and the substantial-N revision.

## What's NOT on the roadmap (deliberately)

- Long-form conversational memory clustering. Explicitly out of scope per `docs/finding-longmemeval-regression.md`.
- Coreference resolution. Explicitly a negative result per `docs/finding-coref-doesnt-help.md`.
- Fine-tuning a custom embedder for paraphrase detection. Outside the wedge thesis. Would require a labeled corpus plus ongoing training.
- Competing with classical entity resolution tools (Senzing, Tilores, Reltio) on database-style normalization. Different category, different buyer.
- Building a graph backend. The proxy is middleware to existing graph stores, not a replacement.

## Decision framework: which path

| Signal | Lean toward Path A (proxy as product) | Lean toward Path B (framework as asset) |
|---|---|---|
| Customer conversations already happening | yes | |
| Want to demonstrate framework reusability | | yes |
| Have a specific vertical domain expertise | yes | |
| Want optionality across multiple AI/ML opportunities | | yes |
| Have time and capital for a 12-18 month commercial build | yes | |
| This is a portfolio piece + career signal | | yes |
| Strong feeling that the proxy is the right wedge | yes | |

Both paths are valid. The framework's value is independent of which one you pick. Path B uses the framework directly. Path A relies on the framework to keep the proxy honest (which it already did once).
