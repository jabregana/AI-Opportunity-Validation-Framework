# Roadmap

What's planned next, ranked by leverage. The previous roadmap (planning the multi-tenant track before v0.4.0 shipped) is fully done; this version reflects what's actually next as of June 2026 after the substantial-N revision.

## Context

The project has completed all four evaluation stages on the schema-alignment proxy opportunity. The honest conclusion: incrementally useful for entity-heavy LLM pipelines (real but narrow value), not market-defining. The framework that produced this conclusion is the durable asset. Two paths from here:

- **Path A**: Continue investing in the proxy as a commercial product (build vertical alias maps, run live customer pilots, ship a memory-auditor tool).
- **Path B**: Apply the framework to the next AI/ML/LLM opportunity. The four-stage progression, harness, multi-model ladder, integration shim pattern, and finding-doc culture all carry forward.

The roadmap below covers both paths.

## Immediate next steps (1-2 weeks)

### 1. Complete the substantial-N ladder (Path A, low cost, high signal)
**Why:** The substantial-N revision tested 10 local + gpt-4o. Opus + Gemini Pro/Flash haven't been re-run at N=836 yet. Completes the revised ranking across all four frontier providers.
**Cost:** ~$50 in API + 30 min runtime.
**Output:** Final 14-model substantial-N ranking. Locks in the "7B ties frontier at fraction of cost" headline with all providers.

### 2. Cache-warmed Mem0 latency A/B (Path A, low cost)
**Why:** Current Mem0 latency comparison was confounded by cold/warm Ollama cache. The actual per-call overhead of the wrapper is ~0ms but isn't measured cleanly.
**Cost:** 30 min to re-run with explicit cache warming.
**Output:** Clean overhead number for the integration docs.

### 3. Multi-corpus generalization test (Path A, medium cost)
**Why:** Currently the substantial-N result is on Twitter Financial News only. A second corpus (Reuters financial news, Reddit r/wallstreetbets) would test whether the pattern is corpus-specific.
**Cost:** Few hours to integrate a second dataset + ~$50 in API for cross-model comparison.
**Output:** Multi-corpus version of `docs/finding-substantial-N-revision.md`.

## Medium-term (1-2 months)

### 4. Pharma vertical case study (Path A, real commercial signal)
**Why:** The financial case study (50-entity map → 125-entity map → 836 tweets) demonstrated the pattern in finance. Pharma is the next-highest-value vertical (regulated, big LLM bill at incumbents). Brand-generic drug normalization + FDA Orange Book aliases.
**Cost:** ~1 week to curate a 200-entity pharma alias map; few days to find an appropriate clinical NLP corpus (PubMed abstracts, MIMIC-III with proper access); few hours of benchmark runs.
**Output:** `experiments/case_study_pharma.py` + `docs/finding-case-study-pharma.md`. Demonstrates vertical-transfer of the pattern. Becomes second buyer-facing case study.

### 5. Memory store auditor tool (Path A, land-and-expand)
**Why:** Diagnostic-led GTM. Free tool that scans an existing Mem0/Graphiti/Cognee store, reports fragmentation per entity, suggests alias-map additions. Easier conversation starter than "subscribe to our wrapper."
**Cost:** ~1-2 weeks to build (read from each integration's store API, run NER/embedder over stored memories, output a fragmentation report).
**Output:** `auditor/` package, CLI: `amg-audit --backend mem0 --user trader1`. Generates an HTML report.

### 6. Apply the framework to a second AI/ML opportunity (Path B, the meta-value)
**Why:** The framework's durability is unproven until it's applied to a second opportunity. Candidates:
- **Agent reasoning verification:** trace-based audit of multi-step agent decisions (Niche 2 from the original landscape scan, now partially closed by Neo4j but still has form-factor angles)
- **Real-time graph GC:** Niche 3 from the original scan, still open per the original verification
- **A new opportunity not yet scoped** (e.g. structured-output validation, prompt-injection defenses, multi-modal entity normalization)

**Cost:** 4-6 weeks per opportunity for a complete four-stage evaluation.
**Output:** A second case study applying the same framework. Two case studies establish a pattern.

## Long-term (3+ months)

### 7. Live customer deployment (Path A)
**Why:** All current claims rest on lab benchmarks. A live deployment with a real customer (fintech, pharma, support automation) is what converts the project from "rigorous prototype" to "production-validated middleware."
**Cost:** Months of customer development, contract work, integration support.
**Output:** Customer logo + case study with real cost-savings number from production.

### 8. Vertical alias map subscription business (Path A, the real moat)
**Why:** The proxy code is ~50 lines and not defensible. The vertical alias maps (financial 500+ entities, pharma 10k+ drugs, legal citations, B2B SaaS customer normalization) ARE the moat. Subscription-based delivery + quarterly updates.
**Cost:** Ongoing curation. Requires domain expertise per vertical.
**Output:** Recurring revenue. Plausibly $1-10M ARR at scale across multiple verticals.

### 9. Open-source community + brand (Path A, distribution moat)
**Why:** The Datadog/Sentry playbook: give the engine away, sell the data and the service. Requires sustained community investment (PRs, conference talks, content marketing).
**Cost:** Multi-year. Probably needs a dedicated DevRel person.
**Output:** Brand recognition as "the entity normalization people" for AI engineers.

## Items from the original roadmap that are now done

For reference, the original roadmap planned the multi-tenant track that has since fully shipped:

- ✅ v0.4.0 source-attributed resolution — multi-tenant per-source isolation
- ✅ v0.4.1 cross-source consensus via Jaccard
- ✅ v0.4.2 lazy consensus (production-shape design)
- ✅ v0.4.3 AND-rule safety
- ✅ v0.4.4 adaptive introspection
- ✅ v0.5.0 bug fixes from multi-tenant Tier B
- ✅ v0.5.1 EntityNormalizer service API
- ✅ v0.5.2 Mem0PreNormalized wrapper
- ✅ v0.5.3 singleton-aware variant
- ✅ v0.5.4 README + CASE-STUDY middleware reframe
- ✅ v0.5.5 ANN index (28× single-tenant speedup)
- ✅ v0.5.6 NER preprocessor (with negative result on LongMemEval)
- ✅ v0.5.7 multi-tenant ANN (6.88× speedup)
- ✅ v0.6.0 Graphiti and Cognee integration shims

Plus the 24 finding docs + 8+ standalone experiments scripts + framework reframe + substantial-N revision.

## What's NOT on the roadmap (deliberately)

- ❌ Long-form conversational memory clustering — explicitly out of scope per `docs/finding-longmemeval-regression.md`
- ❌ Co-reference resolution — explicitly negative result per `docs/finding-coref-doesnt-help.md`
- ❌ Fine-tuning a custom embedder for paraphrase detection — outside the wedge thesis (would require labeled corpus + ongoing training)
- ❌ Competing with classical entity resolution tools (Senzing, Tilores, Reltio) on database-style normalization — different category, different buyer
- ❌ Building a graph backend — we are middleware to existing graph stores, not a replacement

## Decision framework: which path

| Signal | Lean toward Path A (proxy as product) | Lean toward Path B (framework as asset) |
|---|---|---|
| Customer conversations already happening | ✓ | |
| Want to demonstrate framework reusability | | ✓ |
| Have a specific vertical domain expertise | ✓ | |
| Want optionality across multiple AI/ML opportunities | | ✓ |
| Have time/capital for a 12-18 month commercial build | ✓ | |
| This is a portfolio piece + career signal | | ✓ |
| Strong feeling that the proxy is the right wedge | ✓ | |

Both paths are valid. The framework's value is independent of whether you pursue Path A or B — Path B uses the framework directly; Path A relies on the framework to keep the proxy honest (which it already did once).
