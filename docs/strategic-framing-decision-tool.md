---
type: strategic-analysis
date: 2026-06-08
status: PROPOSAL
---

# Strategic framing: from research framework to decision tool

This doc responds to a substantive analyst review of the framework that surfaced the most consequential strategic gap to date. The analyst's framing (paraphrased):

> "The framework is practically useful, but not yet as a product. Today it is best described as a decision-making framework for AI investments, not an AI development framework. The strongest future version would connect: Agent mechanism -> Statistical effect -> Engineering cost -> Business value. When you can answer all four in one report, that's when executives and product leaders will start reaching for it regularly."

The analyst is right. This doc maps that framing against what the framework currently produces, identifies the gaps honestly, and proposes concrete additions to close them.

## What the analyst got right

Three specific points worth repeating, because they reshape the framework's positioning:

1. **The framework answers "is this opportunity real?" but executives need "what should I do next?"** These are different questions. The first is a research output; the second is a budget decision.

2. **Three audiences with different needs**:
   - **AI startups** picking one of six product ideas: need fast triage to kill 5 and fund 1
   - **Enterprise AI teams** weighing where to spend engineering effort: need apples-to-apples comparison of mechanisms by lift-per-dollar
   - **Frontier model teams** running internal eval programs: need a new category of "agent-systems science" tooling (most internal evals stop at model evaluation)

3. **The unit of value is wrong today**. The framework evaluates *mechanisms* (prompt strategy, recovery policy, memory approach). Companies buy *business outcomes* (conversion lift, support deflection, resolution time, cost reduction). The bridge between them is not built.

## Where the framework already delivers vs where it does not

Honest scorecard against the analyst's "mechanism -> statistical effect -> engineering cost -> business value" bridge:

| Layer | Current state | Gap |
|---|---|---|
| **Mechanism evaluation** | **Strong.** Six dimensions, variant ABC + factory pattern, statistical harness (paired bootstrap, LORD++ FDR, CIs). | None at this layer. |
| **Statistical effect size** | **Strong.** Per-dimension UC gates with point estimates. Cross-dim full-matrix experiment with bootstrap CIs (added today). | None major. |
| **Engineering cost** | **Missing.** No estimates of build-effort per variant. Finding docs say "this works" but not "this costs N engineer-weeks." | Big gap. |
| **Business value** | **Missing.** Completion-rate lift is a proxy for "system works better." It does not translate to revenue, deflection, conversion, or any business KPI. | Bigger gap. |

The framework excels at the top two layers. The bottom two are absent. The analyst's point is that **the bottom two layers are where business decisions actually live**.

## What this means for positioning

The framework's narrative in `FRAMEWORK.md` currently says (paraphrased):

> "A framework for evaluating whether AI agent opportunities are real before spending six months building them. The first opportunity tested was a schema-alignment proxy. Two more opportunities (graph GC, recovery policy) followed. All six dimensions of an agent system now produce finding docs and benchmark numbers."

That is true. It is also the "very smart research" framing the analyst flagged.

The reframed positioning, if the proposals below land:

> "A decision-making framework for AI agent investments. For a given product surface, it produces a ranked list of mechanism investments by (statistical lift, engineering cost, business value). Use it before any engineering-quarter planning meeting to decide which of six candidate workstreams to fund."

Same framework. Different positioning. The audience shifts from researchers to AI platform leads, CTOs, and product leaders.

## Proposed additions (in priority order)

Five additions, ordered by smallest credibility-lift-per-effort first.

### 1. Engineering-cost field on every variant (small, high leverage)

Add a `build_cost_estimate` field to every `*Variant` class:

```python
class IntentClassifiedToolVariant(ToolVariant):
    name = "tool-v0.1.1-intent-classified"
    build_cost_estimate = {
        "engineer_weeks": 2.0,
        "ongoing_maintenance_per_quarter_weeks": 0.5,
        "infra_cost_per_million_calls_usd": 0.0,  # this variant is regex-only
        "confidence": "high",  # researcher's estimate; revise from real builds
    }
```

Surface this in every finding doc: "v0.1.1 lifts completion +8pp at 2 engineer-weeks build cost." That single line converts a research finding into a decision input.

**Effort to build**: a few hours. Most variants already have implicit estimates in finding docs; this codifies them.

### 2. Business-KPI mapping per opportunity (medium effort, very high leverage)

Add `docs/business-kpi-mapping-<opportunity>.md` for each opportunity that maps the technical metric to candidate business KPIs:

```markdown
# Business KPI mapping: graph-GC opportunity

Technical metric: store-size reduction percentage.

Candidate business KPI bridges:
  - Memory infrastructure cost: 84.96% store reduction at 1M user scale
    corresponds to ~$X/month savings on Neo4j/vector-store hosting
    (assuming Y$ per stored entity/month at the user's pricing tier).
  - Retrieval latency: smaller store -> shorter index lookups ->
    +Z ms p99 reduction on agent response time -> A% conversion lift
    on time-sensitive product surfaces (per published benchmarks B, C).
  - Engineering toil: pruning that today is a manual quarterly task
    becomes automatic -> N hours/quarter of SRE time freed.

Confidence: low (numbers above are illustrative, not measured).
Calibration plan: pilot with one design partner; measure
infrastructure spend before/after for one quarter.
```

The doc itself is honest about its uncertainty. Even a low-confidence bridge is a meaningful step up from "we don't talk about business KPIs at all."

**Effort to build**: 4-8 hours per opportunity. Six opportunities (one per dimension) = ~one work-week.

### 3. Investment-prioritization tool (medium effort, biggest leverage)

A new experiment script: `experiments/investment_prioritization.py` that:

1. Reads the cost-weighted cross-dim matrix output (already produced)
2. Reads per-variant `build_cost_estimate` fields (proposal 1)
3. Reads per-opportunity business-KPI bridges (proposal 2)
4. Produces a ranked list of investments by **ROI = (lift * business_KPI_multiplier) / engineering_cost**

Output looks like:

```
INVESTMENT PRIORITIZATION REPORT

Rank  Variant                           Lift   Build cost      ROI    Verdict
  1   recovery-v0.1.1-fallback-chain   +14pp   1 eng-week    HIGH    FUND NOW
  2   prompt-v0.1.4-cot-plus-structured +11pp 0.5 eng-week  HIGH    FUND NOW
  3   policy-v0.1.3-handoff             +19pp 2 eng-weeks    MED    FUND Q+1
  4   tool-v0.1.2-intent-plus-helper    +5pp  3 eng-weeks    LOW    DEFER
  5   tool-v0.1.0-budget-bucketed       -47pp                NEG    DO NOT BUILD
```

This is the artifact executives reach for. It is the "budget allocation tool" the analyst named.

**Effort to build**: 1-2 days if proposals 1 and 2 are in place.

### 4. Per-audience report templates (small, medium leverage)

Three templates that re-shape the cross-dim matrix data for each audience:

- `templates/startup-triage.md`: "You have six product ideas. Here are the ones to kill in the first two weeks."
- `templates/enterprise-roi.md`: "You have N engineering quarters to spend. Here is your ranked investment list."
- `templates/frontier-eval.md`: "Here is the agent-systems-science benchmark suite your evaluation team should adopt."

Each template renders from the same underlying data. They differ in framing and detail level.

**Effort to build**: a few hours each.

### 5. Reframed `FRAMEWORK.md` and `README.md` (small effort, biggest narrative leverage)

Rewrite the top of `FRAMEWORK.md` and `README.md` around the decision-tool framing. The architecture and the case studies stay; the positioning shifts.

Key narrative anchors to preserve:
- The four-stage discipline (still the rigor argument)
- The six-dimension architecture (still the comprehensiveness argument)
- The cross-dim findings (now the decision-tool proof point)

Key narrative anchors to add:
- "Use this before your next quarterly planning meeting"
- "Outputs a ranked investment list, not a research report"
- "Connects mechanism evaluation to business value through engineering-cost weighting"

**Effort to build**: a few hours.

## What can be shipped today vs deferred

Today's deliverable (separately committed in this batch):

- **Cost-weighted cross-dim matrix** (`experiments/cross_dim_cost_weighted.py`) with bootstrap CIs is a partial step toward proposal 3. Already produces (cost-per-completion, completion) Pareto frontier with CIs.
- **Real-LLM Stage 3 scaffold** (`experiments/cross_dim_real_llm_stage3.py`) is the bridge from synthetic to real measurement that the analyst flagged as needed for credibility.
- **This strategic analysis doc** records the positioning shift the analyst proposed and the concrete additions to support it.

Not done in this batch:

- Proposals 1, 2, 4: engineering-cost fields, business-KPI mapping docs, audience report templates
- Proposal 3: the investment-prioritization tool itself
- Proposal 5: the reframed FRAMEWORK.md / README top section (the underlying scorecard tables are still load-bearing and stay as is for now)

These are the natural next iteration. The cost-weighted matrix experiment + this doc are the foundation.

## What the framework's pitch becomes

Without the proposals, the framework's strongest pitch today is:

> "A statistical evaluation framework for AI agent opportunities. Surfaces cross-dimension interactions that single-dim benchmarks miss. Produces a deployment recommendation backed by 72 configurations of empirical data."

With the proposals, the pitch shifts to:

> "A decision-making framework for AI agent investment prioritization. For your product surface, it produces a ranked list of where to spend the next engineering quarter, with statistical confidence intervals and business-KPI projections. Use it before quarterly planning to convert opinion into evidence."

The second pitch is what the analyst saw in the framework's bones and named explicitly. The framework's architecture already supports it. The remaining work is bridge-building between layers, not rebuilding the engine.

## Honest limits the analyst's framing also surfaces

Two limits worth naming:

1. **The simulator may not generalize to real LLMs.** Every Stage 2 finding in this project is a simulator output. Real-LLM Stage 3 (proposal: extend `experiments/cross_dim_real_llm_stage3.py` past stub to real API calls) is the bridge. Until that lands, the framework's recommendations are "what the simulator says works," not "what real LLMs do."

2. **The business-KPI bridge will be domain-specific.** A graph-GC reduction means very different things at a fintech vs a clinical-NLP vs a customer-support vendor. The framework can produce the technical Pareto frontier; the business-KPI overlay must be co-authored with a domain partner. Proposal 2 acknowledges this by making each business-KPI mapping doc explicitly "researcher's estimate; calibrate from real deployment data."

The analyst's positioning is achievable. The proposals above are the most direct path. Two pieces (cost weighting, real-LLM scaffold) ship in this batch; the rest are the next iteration.

## Pointers

- Cost-weighted matrix experiment: `experiments/cross_dim_cost_weighted.py`
- Real-LLM Stage 3 scaffold: `experiments/cross_dim_real_llm_stage3.py`
- Cross-dim full matrix (the foundation): `experiments/cross_dim_full_matrix.py`
- Architecture doc: `docs/six-dimensions-architecture.md`
- Framework narrative: `FRAMEWORK.md`
