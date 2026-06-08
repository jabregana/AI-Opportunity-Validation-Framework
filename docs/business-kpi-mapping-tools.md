---
type: business-kpi-mapping
opportunity: tools
date: 2026-06-08
confidence: low
---

# Business KPI mapping: tool-set composition

Bridges the framework's technical lift on the tools opportunity to candidate business KPIs. **Confidence: low** (the tools dimension's variants all flagged DO-NOT-BUILD in cross-dim; the business case is for a FUTURE v0.2.0 with embedding classifier, not current variants).

## Technical metric

**Joint completion rate** at task-execution time given a particular tool-set composition. Current Stage 2 finding: every existing tools variant LOSES vs baseline in cross-dim composition. The wedge IS real but unrealized: the right tool-set composition could deliver substantial cost savings + completion improvement.

## Candidate business KPI bridges (for a hypothetical v0.2.0)

### Bridge 1: per-call inference cost reduction

Anthropic's verified pricing shows tool definitions cost 100+ input tokens each. A 50-tool toolbox costs ~5000 input tokens BEFORE the user's prompt.

- **Mechanism**: a working intent-classifier that narrows from 50 tools to 10 saves ~4000 input tokens per call
- **At Claude Sonnet 4.6 input pricing (~$3/M tokens)**: ~$12K/M calls saved
- **At 10M calls/month**: $120K/month savings ($1.4M/year)
- **Confidence**: high (the cost math is direct), conditional on the classifier actually working

### Bridge 2: completion rate via reduced cognitive overload

Anthropic's documented guidance is that tool-selection accuracy degrades with tool set size (matches the simulator's cognitive-overload model). A well-narrowed tool set should improve selection accuracy.

- **Mechanism**: agents pick the right tool more often when fewer wrong options are available
- **Direct impact**: depends on how much of current failures are tool-selection vs other failure modes
- **Estimated impact**: 3-8pp completion lift POTENTIALLY (cannot be verified by current variants; v0.2.0 needed)
- **Confidence**: low (folklore + Anthropic's hint; not yet measured by the framework on a deployable variant)

### Bridge 3: developer time on tool-set curation

Today's tools workflow is: developer hand-picks which tools to expose per agent / per task / per surface. A working intent classifier eliminates this manual curation.

- **Mechanism**: replaces "engineer decides which 10 of 50 tools to expose for this surface" with "classifier picks them per request"
- **Estimated savings**: 0.5-1 engineer-week per major agent product per quarter (the per-surface curation effort)
- **At $250K/engineer/year**: ~$5K-$10K/quarter saved per agent product
- **Confidence**: medium

## What the current tools variants would need to deliver

For these business KPIs to be realized, the framework needs a tools variant that:

1. Achieves >=95% recall on a realistic workload (current best is 89.82% from v0.1.2)
2. Achieves >=30% precision (current v0.1.2 dropped to 16%)
3. Passes cross-dim composition with no joint-completion penalty

The proposed v0.2.0 (embedding-based classifier) is the candidate. Until it ships, the framework's recommendation is "do not deploy any tools variant" and the business case here is purely prospective.

## Best-fit verticals (when v0.2.0 lands)

Tool-set composition matters most where:

1. **Tool counts are large** (>30 tools, often via MCP server aggregation)
2. **Token cost is a constraint** (high-volume B2C agents at scale)
3. **Tool descriptions are stable enough to embed-cache** (intent classifier benefits from cacheable embeddings)

## Calibration plan (deferred until v0.2.0)

1. Build v0.2.0 with embedding-based classifier
2. Re-run single-dim Stage 2 benchmark; verify recall >= 95%
3. Re-run cross-dim cost-weighted matrix; verify joint config beats baseline
4. Calibrate against a partner deployment (similar shape to memory canonicalization's plan)

Cost: 3-4 engineer-weeks for v0.2.0 build + 4-6 weeks for calibration.

## How this feeds the investment-prioritization tool

The investment tool currently flags all tools variants DO-NOT-BUILD. With this KPI mapping:

- The DO-NOT-BUILD verdict stands; do not ship current variants
- The PROSPECTIVE business case for v0.2.0 is substantial ($1M+/year at high-volume scale)
- A "v0.2.0 prototype" line item appears in the investment-prioritization tool with a future-FUND-NOW status pending the recall fix

This is the most honest possible framing: the framework currently says "don't build these," but the wedge is still real and the right next iteration could unlock a big economic case.

## Pointers

- Tools Stage 2 finding: `docs/finding-tools-stage2-baseline.md`
- Tools v0.1.2 revision (still PARTIAL): `docs/finding-tools-v0.1.2-revision.md`
- Cross-dim full matrix (the verdict gatekeeper): `docs/finding-cross-dim-full-matrix.md`
- Opportunity scan: `docs/opportunity-tools.md`
