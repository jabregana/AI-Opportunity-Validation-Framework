# Finding: Proxies Regress Against No-Proxy Baseline on LongMemEval-S

Status: experimental, June 2026. Statistically confirmed.
Reproduce: pilot script in this doc's appendix.

## Question

The wedge thesis claims the proxies work on "agent memory graphs." LongMemEval-S is a published benchmark for memory in agent contexts. If we ran our best variants on real LongMemEval data, do they help or hurt?

## Setup

LongMemEval-S adapted for clustering (`W-LONGMEMEVAL-S`):
- 500 question-answer pairs
- Each contributes 2 workload entries: `(source="haystack", question_text, qid)` and `(source="answer", answer_text, qid)`
- 1000 entries total across 2 sources, 500 oracle clusters of size 2
- A working variant should cluster the question and its answer together

## Result

| Variant | B-cubed F1 | vs b-raw |
|---|---|---|
| b-raw-identity (no proxy) | 0.6271 | — |
| embed-proxy-v0.1.0 (token) | 0.5626 | -0.065 |
| embed-proxy-v0.3.1 (hybrid + filter) | 0.6167 | -0.010 (p=1.0000, REGRESSION_DETECTED, BLOCK_PR) |
| embed-proxy-v0.4.4-adaptive (best multi-tenant) | 0.6161 | -0.011 (p=1.0000, REGRESSION_DETECTED, BLOCK_PR) |

**All variants regress against b-raw. The harness produces statistically significant REGRESSION_DETECTED for the best variants.**

## Why

The proxy's algorithms (token-overlap hash, embedding cosine on short strings, structural filter) were tuned for SHORT entity/relation names: `WORKS_AT` vs `EMPLOYED_BY`, `Apple Inc` vs `AAPL`. On these inputs the algorithms produce useful merge signals.

LongMemEval has LONG text inputs: full-sentence questions like "What degree did I graduate with?" and full-sentence answers like "Business Administration." On long text:
- Token-overlap fires on common function words ("the", "what", "is")
- Embedding cosine fires on questions with similar templates ("What X did Y?") regardless of underlying entity
- Structural filter does nothing useful

The proxy merges questions together that look similar but reference different oracle ids. b-raw avoids this by giving each unique input its own canonical (singleton clusters); on the LongMemEval clustering metric, that singleton-cluster strategy beats the proxy's spurious merging.

## What this means for the wedge thesis

The wedge thesis from `docs/opportunity.md`:

> A deterministic, no-LLM-in-hot-path schema-alignment proxy that out-competes Mem0's LLM-in-extraction-prompt approach on agent memory graphs.

This needs to be narrowed. The accurate claim is:

> A deterministic schema-alignment proxy for ENTITY AND RELATION NAME NORMALIZATION in property graphs. Validates on workloads where inputs are short surface forms (entity labels, relation names, property aliases). Does NOT generalize to clustering long-form conversational text.

The proxy is a write-path canonicalizer for things like `WORKS_AT → works_at`, `Apple Inc → AAPL → Apple Computer`. It is not a general retrieval or memory system. LongMemEval-style question-answer matching needs different machinery (probably a real retrieval system with re-ranking, not a write-path proxy).

## What does generalize

The harness and statistical framework generalize fully. The same gauntlet (UC-4.1 + UC-4.4 + UC-4.6 + drift metrics + adaptive thresholds) would work for ANY future variant designed for long-text clustering. The infrastructure is reusable; the variants are domain-specific.

The single-tenant proxies (v0.3.1) still pass UC-4.1 / UC-4.4 / UC-4.6 on WikiData property labels at the numbers reported in CASE-STUDY.md. The multi-tenant v0.4.4 still PASS_AND_MERGEs both multi-tenant workloads. None of those previous results change.

## Implication for the project narrative

CASE-STUDY.md and README.md should be updated to scope the claim explicitly: "entity and relation name normalization in property graphs" rather than "agent memory" broadly. The LongMemEval regression should be cited as the boundary of the claim.

This is not a failure; it is a sharper specification of what the project does. A claim "works on agent memory" is too broad to be meaningful; a claim "works on the schema-alignment slice of agent memory, specifically write-path canonicalization of entity and relation names" is precise and defensible.

## Appendix: pilot reproducer

```python
# Requires: dataset downloaded to HF cache via hf_hub_download
from fixtures import workloads
from runner.variants import build
from runner.metrics import alignment

w = workloads.load("W-LONGMEMEVAL-S")
oracle = [(e.input, e.oracle_canonical) for e in w]
for variant_id in ["b-raw-identity", "embed-proxy-v0.3.1", "embed-proxy-v0.4.4-adaptive"]:
    v = build(variant_id)
    for e in w:
        v.align_with_context(e.input, {"source_id": e.source_id})
    if hasattr(v, "consolidate"):
        v.consolidate()
    preds = [(e.input, v.align_with_context(e.input, {"source_id": e.source_id})) for e in w]
    bcubed = sum(alignment.per_item_bcubed_f1(preds, oracle)) / len(preds)
    print(f"{variant_id}: B-cubed={bcubed:.4f}")
```

Or via the harness CLI:

```sh
python -m runner.runner \
  --variant embed-proxy-v0.4.4-adaptive \
  --baseline b-raw-identity \
  --workload W-LONGMEMEVAL-S \
  --use-case UC-4.1 \
  --tier fast
```
