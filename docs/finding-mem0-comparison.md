# Finding: Mem0 v3 OSS Is Not Directly Comparable to a Schema-Alignment Proxy

Status: experimental, June 2026.
Reproduce: `experiments/mem0_baseline.py` with Ollama + a local embedder.

## Question

The wedge thesis from `docs/opportunity.md` was that v0.3.1+ proxies out-compete Mem0's LLM-in-extraction-prompt approach on agent memory graphs. To make that claim defensible, we need a head-to-head: run Mem0 v3 on the same workload (W-WIKIDATA-PROPS), score canonicals with B-cubed F1, compare against v0.3.1.

## Setup

Installed `mem0ai==2.0.4` via pip. Configured with Ollama backend:

```python
config = {
    "llm": {"provider": "ollama", "config": {"model": "qwen2.5vl:7b"}},
    "embedder": {"provider": "ollama", "config": {"model": "all-minilm"}},
    "vector_store": {"provider": "qdrant", "config": {"path": "/tmp/...", "embedding_model_dims": 384}}
}
m = Memory.from_config(config)
```

No paid API key required. Ollama runs locally with the qwen2.5vl LLM and the all-minilm embedder.

## Result

**Mem0 v3 OSS does not produce canonical entity names.** It produces extracted facts as natural-language strings.

Probe with conversational inputs:

| Input | Mem0 output |
|---|---|
| "Apple Inc is a tech company." | `[]` (no extraction) |
| "AAPL is Apple Inc stock ticker." | `["User mentioned AAPL as Apple Inc stock ticker"]` |
| "Apple fruit is grown in orchards." | `[]` |
| "The president of Microsoft Corporation." | `[]` |
| "MSFT is the ticker for Microsoft." | `["MSFT is the ticker for Microsoft"]` |

The outputs are extracted FACTS in sentence form, not canonical identifiers. There is no "canonical entity ID for Apple Inc" coming out of Mem0; instead there is a sentence "User mentioned AAPL as Apple Inc stock ticker" stored in the vector store.

Per-call latency was 0.4-10.5 seconds (qwen2.5vl:7b on Apple Silicon CPU), consistent with the wedge thesis' general claim about LLM-in-loop being slow.

## Why this is the result

Mem0 v3 OSS is a **memory-from-conversation** system. Its API expects natural-language messages and it stores extracted facts (also as natural language) keyed by user_id. It is not an **entity-resolution** system in the schema-alignment sense.

Mem0's proprietary product (Mem0^g, Graph Memory) does build a structured entity graph with canonical IDs, but **graph memory was removed from the OSS distribution in v2.0.0 / v3.0.0** per maintainer commentary in `docs/opportunity.md`. The proprietary version is not accessible without a Mem0 commercial agreement.

## Implication for the wedge thesis

Two things to acknowledge:

1. **The literal "head-to-head against Mem0 on the same workload" is not possible with OSS Mem0.** The two systems address different problems (memory-from-conversation vs entity-canonicalization). Forcing one to do the other's job is a category error.

2. **The wedge thesis should be sharpened.** The accurate framing is not "we beat Mem0 v3 OSS on canonicalization." It is "we provide deterministic entity canonicalization that LLM-in-loop memory systems (Mem0's commercial graph memory, or any system that uses LLM extraction prompts for normalization) would have to compete with on latency and determinism." The comparison is conceptual, not empirical, until a comparable LLM-in-loop entity resolver is available to benchmark against.

What we CAN show:
- Latency: our 27ms p99 vs Mem0 OSS's 0.4-10.5 second range. Order-of-magnitude faster on the write path even though the systems do different things.
- Determinism: our outputs are reproducible by construction; Mem0's depend on LLM sampling, temperature, model version.
- The wedge is real, but the right framing is "LLM-free entity canonicalization is a distinct category that did not exist," not "we built a faster Mem0."

## Code

`experiments/mem0_baseline.py` (this commit) ships the Ollama-backed Mem0 setup so anyone can re-run the probe. The script writes results to `runs/mem0_baseline_<timestamp>.json` for inspection.

For a more apples-to-apples comparison, future work could:

1. Get access to Mem0's commercial Graph Memory and benchmark on W-WIKIDATA-PROPS.
2. Implement a from-scratch LLM-in-loop entity resolver (call an LLM per write, ask "what's the canonical form of this entity?"). Compare against v0.3.1 on the same workload. This would be the closest like-for-like apples comparison.
3. Convince an LLM provider to expose deterministic entity resolution as a feature; benchmark against it.

Option 2 is the most tractable and would deliver a defensible apples-to-apples number.
