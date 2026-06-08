---
type: opportunity
dimension: prompt
stage: 1
status: WEDGE-CANDIDATE
date: 2026-06-07
---

# Stage 1 opportunity scan: agent prompt dimension

This is the Stage 1 landscape scan for the **prompt** dimension. The dimension already has scaffolding (`PromptVariant` ABC + `b-default-prompt` baseline at `runner/dimensions/prompt/`).

The prompt dimension is the most contested of the six in 2026: DSPy has made auto-prompt-optimization a serious technical area, prompt-caching APIs from Anthropic / OpenAI have made prompt length a first-order cost concern, and structured-output schemas have blurred the line between prompt and contract. Picking a wedge here requires being honest about what is already covered.

## What the incumbents do today

| Tool / framework | Prompt primitives shipped | Gap relevant to a benchmark |
|---|---|---|
| **DSPy** (Stanford) | Auto-optimizes prompts via BootstrapFewShot, MIPRO, COPRO; signatures + modules abstraction; teleprompters | Optimizes ONE prompt at a time against ONE metric. Does not compare prompt STRATEGIES (CoT vs direct vs structured vs few-shot vs zero-shot) across tasks / models / cost budgets. |
| **LangChain PromptTemplate / ChatPromptTemplate** | Templating, partial variables, message roles, format-string substitution | Templating only. No strategy comparison, no optimization, no cost awareness. |
| **AutoPrompt, APE, OPRO** (research) | LLM-as-optimizer methods that propose-then-evaluate prompts | Research artifacts, not production benchmarks. Optimize one prompt per task. |
| **Anthropic prompt caching** | Marks portions of the prompt as cacheable for hot-path cost reduction | Cost mechanism, not selection. Caches whatever you send; doesn't tell you which prompt strategy is best for a given task. |
| **OpenAI structured outputs / JSON mode** | Forces output to a schema; effectively a prompt-side contract | Contract-side, not strategy-side. Doesn't compare "JSON mode vs free-form + parse" across task classes. |
| **DSPy LMFunctionCompiler / Predict modules** | Wraps signatures into Python functions; modules generate the prompt | Generation, not comparison. |
| **Guardrails AI / Pydantic AI** | Output-schema validation that re-prompts on failure | Validation, not selection or comparison. |
| **Inspect AI prompt-engineering evals** | Evaluates correctness given a fixed prompt | Single-prompt evaluation; not strategy comparison. |
| **Promptfoo / LangSmith eval** | A/B test two prompts on a metric | Closest existing tool. Limited to pairwise; no multi-strategy / multi-model / cost-aware framework. |

## What is missing

DSPy is genuinely strong at the "optimize this prompt against this metric" problem. The remaining wedge is at a different layer: **comparing prompt STRATEGIES under cost and model awareness.**

Specifically, none of the above can answer:

1. **"For task class K on model M with cost budget B, which prompt strategy (CoT / direct / structured / few-shot N=k) is best?"** DSPy optimizes within a strategy; comparison across strategies is hand-coded per project.
2. **"Does the optimal strategy shift across model sizes?"** A 3B local model might benefit from CoT scaffolding that a frontier model treats as noise. No published cross-model strategy comparison.
3. **"What is the cost-quality Pareto frontier per task class?"** Longer prompts (more few-shots, more CoT scaffolding) cost more tokens. At what point does additional length stop buying lift? Nobody publishes this.

Promptfoo is the closest existing tool. It does A/B prompt comparison but is single-task, single-model, and not statistical (no FDR control, no bootstrap CIs, no Pareto frontier).

## Three candidate wedges

### Wedge A: Strategy-comparison benchmark suite (variant ABC + cross-strategy gates)

Build `PromptVariant` implementations for the canonical prompt strategies (direct, CoT, structured, few-shot-1, few-shot-3, few-shot-5, structured+CoT) and benchmark each on a task-completion workload across the multi-model ladder. Same harness shape as the recovery + tools dimensions.

- **Pros**: The `PromptVariant` ABC already exists. The multi-model ladder is already wired. The statistical harness carries over.
- **Cons**: Risks overlap with DSPy if DSPy ever ships a "compare strategies" mode (they could; their architecture supports it).
- **Incumbent overlap**: Partial with DSPy (DSPy optimizes within a strategy; this compares across). Some overlap with Promptfoo (this adds the cost-aware Pareto framing).

### Wedge B: Cost-aware prompt selection (Pareto frontier)

Specifically focus on the cost-vs-quality tradeoff. Given a task class, plot the Pareto frontier of (prompt-token-cost, completion quality). Identify the knee. This is a more specific framing of Wedge A.

- **Pros**: Highly actionable result. Every API user immediately benefits.
- **Cons**: Subset of Wedge A; should probably be done as part of A rather than separately.
- **Incumbent overlap**: None doing this rigorously.

### Wedge C: Prompt-caching effectiveness benchmark

With prompt caching now mainstream (Anthropic, OpenAI), benchmark which prompt structures cache best and how cache hit rates affect total cost over an agent run.

- **Pros**: Specific to a 2025-2026 development. Practical for production agent operators.
- **Cons**: Highly provider-specific. Caching behavior may shift over time as providers tune their caches.
- **Incumbent overlap**: Nobody is doing this publicly, but the work might be considered "infrastructure benchmark" rather than "agent benchmark."

## Pick: Wedge A (strategy-comparison benchmark) with Wedge B framing baked in

For three reasons:

1. **It is the broadest useful claim that does not directly overlap DSPy.** DSPy optimizes within a strategy; this compares across strategies. The two are complementary; a DSPy user could use this wedge's output to pick which strategy to feed DSPy.
2. **The cost-aware framing (Wedge B) is the differentiator.** Without cost-awareness, Wedge A risks being "just like Promptfoo but with more strategies." With cost-awareness, it becomes "the Pareto-frontier benchmark for prompt strategies that nobody has published."
3. **It uses every part of the existing framework.** Statistical harness, variant ABC, multi-model ladder, finding-doc culture. No new framework infrastructure needed.

Wedge C (prompt-caching) is a worthwhile follow-up but its provider-specific nature makes it less generalizable.

## Out-of-scope for Stage 1

- **Prompt-injection / safety benchmarks** (separate dimension; would be its own opportunity scan)
- **Cross-language prompt engineering** (English-only for the pilot)
- **Embedded prompt strategies in fine-tuned models** (training-time concern)

## Stage 2 plan (sketch, not committed)

If Wedge A holds up, Stage 2 looks like:

**Day 1**: Verify the incumbent state. WebFetch DSPy's BootstrapFewShot source. Read Promptfoo's eval format. Read Anthropic prompt-caching pricing data (already have from the tools scan).

**Day 2**: Build the synthetic task-completion workload. Each task has a goal + ground-truth answer + token-level cost model. Tasks span 3-5 task classes (reasoning, retrieval, structured-extraction, classification, code) so strategy effectiveness can be measured per class.

**Day 3**: Build five-to-seven pilot prompt variants:
- `b-default-prompt` (already in `runner/dimensions/prompt/b_noop.py`)
- `prompt-v0.1.0-cot` (zero-shot chain-of-thought)
- `prompt-v0.1.1-direct-structured` (force JSON output, no CoT)
- `prompt-v0.1.2-few-shot-1` (one example)
- `prompt-v0.1.3-few-shot-3` (three examples)
- `prompt-v0.1.4-cot-plus-structured` (CoT scaffolding + structured output)

**Day 4**: Build the runner with UC gates:
- UC-PROMPT-1: completion-rate lift vs default
- UC-PROMPT-2: cost-per-correct-completion <= baseline * 1.5 (cost-aware)
- UC-PROMPT-3: per-task latency
- UC-PROMPT-4: variance reduction (CoT often has lower variance even if mean is similar)

**Day 5**: Run benchmark across the multi-model ladder + write finding doc with the cost-quality Pareto frontier per task class.

If Day 5 passes, Stage 3 runs on a real public benchmark (GSM8K subset, HotpotQA subset) with the same variants.

## Pointers

- Architecture: [`six-dimensions-architecture.md`](six-dimensions-architecture.md)
- Existing scaffolding: `runner/dimensions/prompt/{base.py, b_noop.py, __init__.py}`
- Framework narrative: [`../FRAMEWORK.md`](../FRAMEWORK.md)
- Multi-model ladder (will be reused): `experiments/ladder_sweep_real_data.py`
- Precedents for this scan's shape: [`opportunity.md`](opportunity.md), [`opportunity-graph-gc.md`](opportunity-graph-gc.md), [`opportunity-recovery.md`](opportunity-recovery.md), [`opportunity-tools.md`](opportunity-tools.md)
