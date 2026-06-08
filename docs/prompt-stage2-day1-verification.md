---
type: stage-note
opportunity: agent prompt dimension
stage: 2
day: 1
date: 2026-06-08
---

# Prompt Stage 2 Day 1: incumbent verification

Goal: verify the incumbent named most prominently in the prompt-dimension opportunity scan (DSPy) before building Stage 2 pilot variants. Day 1 of the Stage 2 plan in [`opportunity-prompt.md`](opportunity-prompt.md).

## Verified: DSPy BootstrapFewShot teleprompter

Source: `stanfordnlp/dspy` repo, `dspy/teleprompt/bootstrap.py` (raw GitHub fetch, 2026-06-08).

What it ships:

| Mechanism | What it does |
|---|---|
| `BootstrapFewShot.compile(student, *, teacher=None, trainset)` | Bootstraps demonstrations for an existing prompt signature |
| `max_bootstrapped_demos`, `max_labeled_demos` | Cap quantity of demonstrations (not token budget) |
| `_bootstrap_one_example()` | Validates demonstrations against a user-supplied metric |
| Per-module optimization (Predict, ChainOfThought, etc) | Auto-generates few-shot examples for a single module type |

What it does NOT ship:

- **No cross-strategy comparison.** BootstrapFewShot operates within ONE strategy. It refines few-shot demonstrations for an existing `ChainOfThought` module or an existing `Predict` module; it does not benchmark `ChainOfThought` vs `Predict` against each other. The wedge framed in the opportunity scan (strategy-comparison benchmark) is intact.
- **No token-budget constraint.** `max_bootstrapped_demos` is a quantity cap, not a cost cap. There is no API for "find the best prompt that fits in N tokens."
- **No Pareto-frontier surface.** Optimization produces a single best prompt for a single metric; no way to report (cost, quality) trade-off curve.
- **No multi-model comparison.** Single LM at compile time.

This confirms the opportunity scan's core hypothesis: DSPy is genuinely strong at optimization WITHIN a strategy, but the across-strategy + cost-aware comparison is missing.

## Inferred: Promptfoo (not live-verified this round)

The opportunity scan flagged Promptfoo as the closest existing tool with pairwise prompt comparison. Day 1 verification of Promptfoo is deferred to the deep-research workflow. Inferred shape from training knowledge:

- A/B test two prompt variants on a user-supplied dataset
- Supports multi-provider model comparison
- Reports pass/fail per assertion; does not surface cost-quality Pareto frontier or statistical confidence intervals

If Promptfoo has shipped Pareto-frontier or paired-bootstrap surfaces since the scan, the wedge narrows. Worth checking before Stage 3.

## Inferred: Anthropic prompt caching (verified pricing in tools Day 1)

Anthropic prompt-caching pricing was verified in [`tools-stage2-day1-verification.md`](tools-stage2-day1-verification.md). Caching is a cost mechanism, not a strategy-selection mechanism; it caches whatever prompt the developer sends. The cost-aware framing of the prompt wedge directly engages with caching: a long prompt that caches well may dominate a short prompt that does not.

## Not yet live-verified (deferred)

- Promptfoo source / current Pareto support
- AutoPrompt / APE / OPRO implementations
- LangSmith eval surface for prompt-A/B
- DSPy MIPRO and COPRO teleprompters (likely same within-strategy scope as BootstrapFewShot)
- Guardrails AI re-ask loops as prompt-side primitives

Documented as deferred; would benefit from a deep-research workflow call before Stage 3 publication.

## Decision

The wedge is intact. Proceed to Day 2 (build the synthetic task-completion workload with category + difficulty + ground-truth structure). No edits needed to the opportunity scan's Wedge A pick.
