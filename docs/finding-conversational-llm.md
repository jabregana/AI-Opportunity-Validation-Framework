# Finding: Proxy lift holds on multi-turn conversational extraction (smaller magnitude)

**Status:** confirmed, smaller-magnitude version of the single-sentence finding
**Workload:** 10 synthetic multi-turn conversations, 6 oracle entities, 20-alias map
**Models:** llama3.2:1b (1.2B), llama3.2:3b (3.2B), qwen2.5:14b (14.8B) via local Ollama
**Script:** `experiments/conversational_llm_bench.py`

## Setup

Built 10 short multi-turn dialogues (4-6 turns each) discussing 1-3 entities per conversation. Each entity is mentioned multiple times using different surface forms (AAPL, Apple, Apple Inc, Apple Computer for Apple Inc) and via co-referential expressions ("they", "the company", "both companies", "all three"). Co-reference resolution is the LLM's job; the proxy does not touch pronouns.

Task: ask the LLM to list every distinct company mentioned in the conversation. Compute set-level precision / recall / F1 vs the oracle set per conversation, then macro-average across all 10 conversations.

Fair comparison: the LLM's raw outputs are canonicalized via the alias map BEFORE the set comparison. This way the no-proxy condition is not penalized for saying "AAPL" when the oracle is "Apple Inc"; both conditions are scored on the same canonical-form output set. The proxy's advantage shows up only where it reduces fragmentation that the LLM would otherwise emit.

## Result

| Model | no proxy macro-F1 | with proxy macro-F1 | Δ F1 | per-call latency |
|---|---|---|---|---|
| llama3.2:1b | 0.4071 | 0.4467 | +0.0395 | 250 ms → 120 ms |
| llama3.2:3b | 0.8667 | 0.9333 | +0.0667 | 280 ms → 130 ms |
| qwen2.5:14b | 0.7533 | 0.9333 | +0.1800 | 600 ms → 310 ms |

## Pattern from the single-sentence finding holds (with smaller magnitude)

The single-sentence finding (`docs/finding-small-llm-quality.md`) showed +0.23 to +0.55 B-cubed lift across the same 1B/3B/14B models. The multi-turn lift is +0.04 to +0.18, smaller but pointed in the same direction. Three properties are preserved:

1. The 14B model gets the LARGEST lift (+0.18). Larger LLMs still faithfully echo input variation; the proxy still compensates.
2. With proxy, the 3B and 14B models CONVERGE to the same F1 (0.9333). The proxy lifts both up to the LLM's instruction-following ceiling on this task.
3. The proxy is ~2x faster per call across all model sizes (the LLM has less to reason about).

## Why the magnitude shrunk

Two structural reasons.

**Co-reference is doing canonicalization work the proxy does not.** When a conversation mentions "Apple Inc" early and later says "they" or "the company", the LLM resolves the co-reference internally. Co-referential expressions are the LLM's responsibility regardless of whether the proxy is in front. On a conversation where most entity mentions are co-references rather than aliases, the proxy has fewer surface forms to normalize.

**The set-extraction task has a different upper bound than per-mention clustering.** The single-sentence task scored per-mention coherence via B-cubed F1; fragmentation directly hurts the score. The conversational task asks for the SET of entities and scores set-F1; if the LLM produces five aliases for one entity but the canonicalization step collapses them on the post-hoc score, the only penalty is precision (extra distinct entities). The proxy primarily helps recall (the LLM is less likely to MISS an entity when its name has been pre-normalized to the canonical) and precision (fewer spurious distinct outputs).

## Where the 1B model gets stuck

The 1B model only reaches 0.4467 macro-F1 even with proxy. Looking at its outputs, it struggles with the extraction format (listing one per line consistently) and sometimes hallucinates entities not in the conversation. This is an LLM capability limit, not a proxy limit. A larger model recovers immediately (3B reaches 0.9333 with proxy).

## Commercial implication

Multi-turn confirms that the proxy delivers a quality lift in realistic conversational shapes, not only in synthetic single-sentence inputs. The lift's magnitude depends on how much of the entity reference burden is on surface aliases (which the proxy handles) vs co-reference (which it does not). For high-alias-density domains (financial chat with ticker variants, support tickets with product codes, technical chat with API/library aliases) the proxy's value persists. For low-alias-density domains (general conversation with mostly explicit canonical names + pronouns) the value shrinks.

## What this benchmark does NOT prove

- The 10-conversation workload is too small for statistical significance claims; the pattern is consistent across model sizes but the absolute numbers are noisy.
- No real conversational dataset (LongMemEval, Multi-WOZ, DSTC) was used. The conversations are synthetic and may not match the alias / co-reference distribution of any specific real deployment.
- No co-reference baseline was tested. Adding a co-reference resolver (e.g. spaCy neuralcoref or LLM-based) before the proxy would likely close the remaining gap on the 1B model and shrink the gap further on larger models.
- The alias map is fully closed (every alias the LLM might see is in the map). Real deployments have open-world aliases the map misses; those rely on the embedding-based EntityNormalizer rather than the static mention_map. That regime is untested here.

## Next experiments worth running

1. **Real conversational data with sparse alias coverage.** Use a subset of LongMemEval or a real chat log; measure the proxy lift when only the top-N domain aliases are in the map.
2. **Co-reference resolver upstream of the proxy.** Add a spaCy co-ref pass and measure the additional lift.
3. **Open-world aliases via EntityNormalizer.** Test the embedding-based path on aliases NOT in the static map; this is the v0.3.1+v0.5.5 codepath rather than the Mem0PreNormalized mention_map shortcut.
