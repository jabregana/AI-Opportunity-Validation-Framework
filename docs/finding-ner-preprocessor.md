# Finding: NER preprocessor opens the proxy to long-form text

**Status:** infrastructure landed, downstream evaluation pending
**Source:** v0.5.6 (commit pending)
**Closes:** the architectural piece of the LongMemEval-S regression documented in `docs/finding-longmemeval-regression.md`

## Motivation

The proxy normalizes short surface forms. On long-form text (chat transcripts, articles, support tickets, conversational memory) it had no way to identify the spans worth normalizing, which meant deploying it in front of a chat memory system was a no-op at best. LongMemEval-S confirmed the regression empirically: every variant trailed b-raw on conversational text.

v0.5.6 adds a preprocessor layer that converts long-form text into entity spans, which the proxy then normalizes individually. The proxy itself is unchanged.

## Design

A preprocessor is a callable matching:

```python
Callable[[str], list[tuple[int, int, str]]]
```

returning (start, end, surface) spans into the input text. This is exactly the signature `Mem0PreNormalized.mention_extractor` already accepted, so any preprocessor drops straight in. Three concrete implementations:

1. **`RegexNERPreprocessor`** (pure stdlib). Picks up Title Case multi-word runs (with optional corporate suffixes), all-caps acronyms in a configurable length band, and a user-supplied allow-list. Overlap-deduplicates by length and priority. Honest about being heuristic: catches false positives on sentence-starting Title Case, misses lowercase brand names, no homograph disambiguation. Good baseline for tickers / codes / well-known product names.

2. **`SpacyNERPreprocessor`** (optional `[ner]` extra). Wraps spaCy's `nlp.ents`. Default keep-set filters out value entities (DATE, MONEY, etc.) and keeps PERSON / ORG / GPE / LOC / PRODUCT / WORK_OF_ART / EVENT / LAW / LANGUAGE / NORP / FAC. Lazily loads the model on first call.

3. **`TransformersNERPreprocessor`** (optional `[ner-transformers]` extra). Wraps a HuggingFace `pipeline("ner", aggregation_strategy="simple")`. Default model `dslim/bert-base-NER` emits PER / ORG / LOC / MISC. Lazily constructed on first call.

All three are exposed at `runner.service.preprocessors` and lazy-re-exported from `runner.service` so the common import (`from runner.service import RegexNERPreprocessor`) works.

## Integration

```python
from mem0 import Memory
from runner.service import EntityNormalizer, RegexNERPreprocessor
from runner.service.integrations import Mem0PreNormalized

norm = EntityNormalizer("embed-proxy-v0.3.1")
pre = RegexNERPreprocessor(allow_list=["AAPL", "MSFT", "TSLA"])

m = Mem0PreNormalized(Memory(), norm, mention_extractor=pre)
m.add(
    "On Monday the trader bought AAPL and watched Apple Inc closely.",
    user_id="trader1",
)
# Mem0 receives text where AAPL and Apple Inc have been normalized to
# their canonical forms before the LLM extraction prompt runs.
```

## Demo output

`experiments/ner_long_form_demo.py` runs the regex preprocessor over a synthetic trading log. On the 5-sentence input it extracts 12 spans including the four tickers (AAPL, MSFT, TSLA) and the corporate names (Apple Inc, Microsoft Corp, Microsoft Corporation). It also picks up four false positives at sentence-starting Title Case (On Monday, He, Later, Thursday). The false positives are by design: the regex is a baseline. Users who need precision swap in `SpacyNERPreprocessor` or `TransformersNERPreprocessor`.

## What this does not yet do

- **No re-run of LongMemEval-S.** The infrastructure is in place to feed long-form text through the proxy, but the LongMemEval head-to-head against b-raw with the preprocessor in front has not yet been measured. The expectation is that the regression closes for entity-mention questions and stays present for paraphrase-clustering or full-passage questions (which is outside the proxy's design scope regardless).
- **No co-reference resolution.** "Apple Inc... they..." is currently two separate spans (Apple Inc + nothing for "they"). A co-ref layer would feed the proxy more correct mentions; deferred.
- **No span-merge with the proxy's structural filter.** If a preprocessor emits "Apple" and "Apple Inc" overlapping, the higher-priority span wins; the proxy's structural filter is then applied to each normalized form independently. A future variant could pass the full span list to the proxy and let it resolve which to canonicalize.

## Tests

11 new tests covering regex extraction (title case, acronyms, allow-list, overlap dedup, span validity, parameter validation), Mem0 integration, and missing-dep error paths for the model-backed preprocessors.

## Next

- Re-run UC-4.7 (held-out generalization) with `RegexNERPreprocessor` in front of v0.3.1 on LongMemEval-S. Compare to b-raw with the same preprocessor in front. The honest comparison is preprocessor-on-both, not proxy-with-NER vs raw-text-baseline.
- Try the spaCy preprocessor; measure regex false-positive rate as a baseline.
- v0.5.7: multi-tenant ANN variant (let v0.5.3 inherit the K-scale speedup from v0.5.5).
