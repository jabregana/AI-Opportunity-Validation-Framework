# Finding: Co-reference resolver doesn't help (and may hurt) when run upstream of the proxy

**Status:** confirmed negative result
**Workload:** 10 multi-turn conversations from `conversational_llm_bench` (with co-referential expressions)
**Model:** llama3.1:8b (used for both coref resolution and entity extraction)
**Script:** `experiments/coref_conversational_bench.py`

## Hypothesis going in

The conversational benchmark (`docs/finding-conversational-llm.md`) flagged co-reference as the load-bearing reason the proxy lift shrinks on multi-turn: the proxy normalizes surface forms, but pronouns ("they", "the company") carry entity references the proxy can't see. The hypothesis: adding an explicit co-reference resolver upstream of the proxy would close the gap by rewriting pronouns to entity names BEFORE the proxy normalizes them.

## Setup

Built `LLMCorefResolver`: takes conversation text, sends to a local Ollama LLM with a strict rewrite-only prompt, returns text where pronouns and definite descriptions have been replaced with entity names. Four conditions on the same 10 conversations:

- **A. raw** — no preprocessor, no proxy
- **B. proxy_only** — `mention_map` only (the prior conversational baseline)
- **C. coref_only** — `LLMCorefResolver` only, no proxy
- **D. coref_then_proxy** — resolver upstream of the proxy

## Result

| Condition | Macro F1 | vs A (raw) | vs B (proxy-only) | Extract time |
|---|---|---|---|---|
| A. raw | 0.6774 | — | — | 4.1s |
| B. proxy_only | 0.7333 | +0.0560 | — | 2.8s |
| C. coref_only | 0.6533 | **-0.0240** | -0.0800 | 40.4s |
| D. coref_then_proxy | 0.7267 | +0.0493 | **-0.0067** | 157.5s |

## Three findings

1. **Coref alone REGRESSES** vs raw (-0.0240). The LLM-based resolver introduced noise — sometimes mis-rewrites entity references or hallucinates referents. This is the same precision-vs-recall trade-off seen in the original Opus conversational result, but here it manifests as the resolver INTRODUCING errors instead of catching variation.

2. **Coref + proxy is essentially identical to proxy-only** (-0.0067, well within noise). Adding coref upstream of the proxy does not close the conversational gap. The proxy's contribution is bounded by what the LLM extraction can do on cleanly-mentioned entities; the coref step doesn't add information the LLM didn't already have.

3. **Latency cost is huge.** Coref adds ~12-16 seconds per conversation. For zero quality benefit on this workload, that's a clear net negative.

## Why the hypothesis was wrong

Two compounding reasons:

**The LLM is already doing co-reference internally.** When llama3.1:8b reads a conversation and is asked to extract distinct entities, it resolves "they" and "the company" to the right referent as part of the extraction reasoning. An explicit upstream coref step is redundant — it pre-bakes a decision the LLM was going to make anyway, and any error in the upstream decision propagates.

**The coref resolver itself is an LLM call with its own error modes.** The resolver can hallucinate a referent ("they" → "Apple Inc" when the prior context was actually about Microsoft), mis-resolve definite descriptions, or alter sentence structure in ways that confuse downstream extraction. Net: small introduced error rate, no compensating quality gain.

## When coref preprocessing might still help

The infrastructure (`LLMCorefResolver` and `FastcorefResolver` in `runner/service/preprocessors/coref.py`, with 6 tests covering both) is preserved because there are workloads where it could plausibly help:

- **Very long conversations** that exceed the downstream LLM's context window. Explicit coref pre-resolution may reduce the input size and let the LLM see the relevant entity names directly.
- **Co-reference-heavy domains** like meeting minutes or court transcripts where the entity-to-pronoun ratio is heavily skewed toward pronouns.
- **Models with weak instruction following.** A tiny model might not resolve co-reference internally during extraction. An upstream LLM coref step using a larger model could compensate.
- **Use cases that need explicit entity mentions in the stored memory.** If the downstream system stores raw extracted text and an integrator wants pronouns expanded for retrieval, the coref step IS the right preprocessing.

These are hypotheses; none have been benchmarked. For the schema-alignment-proxy use case as designed, coref preprocessing is empirically not worth the latency.

## What this confirms about scope

The original conversational finding said "co-reference is the LLM's job, not the proxy's." This experiment confirms that statement and adds nuance: even MAKING co-reference an explicit upstream step does not help when the downstream LLM is the extractor. The right scope for the schema-alignment proxy is surface-form alias normalization. Pronoun resolution is downstream of that scope.

## Implications for the project

- The conversational lift documented in `finding-conversational-llm.md` (+0.07 to +0.27 across model sizes) is the realistic ceiling for the proxy on multi-turn dialogue when co-reference is left to the LLM. Adding coref preprocessing does not raise that ceiling.
- The `LLMCorefResolver` and `FastcorefResolver` are kept in the public API for the use cases listed above, with this finding documented as the "not for this" guidance.
- This is one more pinned-down boundary on the proxy's coverage envelope.
