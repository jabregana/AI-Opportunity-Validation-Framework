# Finding: NER preprocessor does not close the LongMemEval-S regression

**Status:** confirmed negative result
**Workload:** W-LONGMEMEVAL-S (1000 entries, 500 oracle clusters)
**Variants:** b-raw-identity vs embed-proxy-v0.3.1
**Preprocessor:** RegexNERPreprocessor (Title Case runs + acronyms)
**Script:** `experiments/ner_longmemeval_compare.py`

## Result

| Variant | no NER | with NER | Δ NER |
|---|---|---|---|
| b-raw-identity | 0.6271 | 0.6271 | +0.0000 |
| embed-proxy-v0.3.1 | 0.6164 | 0.6164 | +0.0000 |
| **Δ proxy vs baseline** | **-0.0107** | **-0.0107** | |

The regression is identical to four decimal places in both configurations.

NER extracted 1353 spans across the 1000 entries and changed 8303 characters of input text during preprocessing, so it was doing real work. The work just had no effect on the metric.

## Why the metric is unchanged

Two compounding reasons.

**The proxy's canonical naming is first-writer-wins.** When the proxy normalizes a span, the canonical it returns is the surface form of whichever input minted that canonical first. For most spans on this workload that mint happens on the same input the span came from, so `normalize(surface) == surface` and the substitution writes the same string back into the text. For repeated spans, the canonical is the original surface form, so the substitution still writes the same string.

The only case where NER substitution would actually change the text is when the proxy maps a surface to a *different* canonical that it had minted earlier from some other alias (e.g. NER sees "AAPL" and the proxy has already minted "Apple Inc" as the canonical for that cluster). On LongMemEval-S the questions and answers do not contain enough cross-input aliasing for that case to fire in volume.

**The metric measures cross-source clustering, not entity normalization.** The W-LONGMEMEVAL-S metric asks whether the question text and its corresponding answer text cluster under the same canonical. The proxy's failure mode on this workload (per `docs/finding-longmemeval-regression.md`) is that it merges DIFFERENT questions that share template words ("What X did Y?"). Entity normalization is the wrong tool for that problem. The questions and the answers do not even share salient entities most of the time ("What degree did I graduate with?" / "Business Administration"); they share semantics, which is what a retrieval system or a sentence embedding clusters on, not what a write-path entity normalizer does.

## What this confirms

The README's good-fit / bad-fit table (added in v0.5.4) already named long-form conversational text as out-of-shape for the proxy. This experiment confirms that adding NER in front does not change that. The v0.5.6 preprocessor is the right tool for the right workload (entity-mention-clustering with multi-alias entities), not a fix for any workload where the proxy regresses.

The wedge thesis is unchanged from `docs/finding-longmemeval-regression.md`: the proxy is for entity and relation name normalization in property graphs, not general conversational memory clustering.

## What would actually move the LongMemEval number

Two paths that the v0.5.x infrastructure does NOT take:

1. **A different evaluation shape.** The clustering-on-(question, answer)-text setup is a poor fit for any entity normalizer. The real LongMemEval task is question answering with retrieval over a haystack. A proxy could plausibly help by canonicalizing entity mentions inside the haystack BEFORE retrieval (so a question about "AAPL" matches haystack passages mentioning "Apple Inc"). Implementing this end-to-end is what `docs/longmemeval-integration-plan.md` outlines and is its own work item.

2. **A different variant.** Sentence-level embedding clustering (e.g. SBERT over each input) is the natural tool for question-answer pair clustering. That is not what any of the current variants do; they are all token + entity-level. Building a sentence-clustering variant would be a different project shape than the schema-alignment proxy.

## Test coverage

The NER preprocessor infrastructure that made this experiment cheap to run is itself covered by the v0.5.6 test suite (`tests/test_ner.py`). The negative result here is a useful validation that the infrastructure does NOT silently inflate the proxy's headline number; the harness reports the unchanged result honestly.
