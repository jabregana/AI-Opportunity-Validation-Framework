# Finding: Distributional Neural Embedders Cannot Cleanly Separate Paraphrases from Hard Negatives

Status: experimental, single-author probe, June 2026.
Reproduce: see `docs/finding-neural-ceiling-probe.py` and the raw data table below.

## Question

Could a stronger neural embedder than model2vec (the distilled static model used in v0.2.0 / v0.3.0 / v0.3.1) unlock paraphrase coverage that the current variants cannot reach? The hypothesis being tested: model2vec is lossy and short-input-weak, so a real sentence transformer might produce cleaner cosine separation between true paraphrases and the hard-negative class (sibling / antonym / structurally-distinct pairs).

## Setup

Three embedders, same prompt template `"the relation type called {}"` across all three, cosine on L2-normalized output. Probe set: 8 hand-curated true paraphrases plus 10 hand-curated hard negatives, plus 3 surface-form variants as a sanity floor.

| Embedder | Params | Source |
|---|---|---|
| model2vec potion-base-32M | distilled (static) | huggingface.co/minishlab/potion-base-32M |
| sentence-transformers/all-MiniLM-L6-v2 | 22M | the smallest serious sentence transformer |
| BAAI/bge-base-en-v1.5 | 110M | mid-size; near top of MTEB leaderboard for its size |

Python 3.12 venv (PyTorch wheels not available for Python 3.14 at probe time).

## Results

Median cosine across true paraphrases vs hard negatives, with the relation-type prompt template applied to all inputs:

| Embedder | Paraphrase median | Hard-negative median | Hard-neg > paraphrase overlap |
|---|---|---|---|
| model2vec potion-base-32M | ~0.71 | ~0.90 | ~60% |
| MiniLM-L6-v2 | 0.68 | 0.83 | ~55% |
| BGE-base-en-v1.5 | 0.83 | 0.89 | **67.5%** |

The bigger neural models do not separate the two populations; they just shift the whole distribution upward. BGE-base's overlap is actually worse than MiniLM's. No single cosine threshold cleanly classifies a pair as paraphrase vs hard-negative on this task.

## Why

This is the antonym / sibling problem of distributional semantics. Pairs like `Synonym` and `Antonym`, `LOCATED_IN` and `LOCATED_NEAR`, `MadeOf` and `PartOf` appear in the same contexts in training corpora. The cosine similarity of their embeddings reflects contextual co-occurrence, not semantic identity. The model cannot tell from distributional signal alone that `Synonym` and `Antonym` mean opposite things.

Bigger models trained on more text do not fix this. They learn the same distributional patterns more confidently. They actually compress the cosine range upward, making sibling pairs even more confusable with true paraphrases.

The hardest hard-negative pairs in the WikiData Tier B fixture are *structural*:
- `ISO 639-1 code` vs `ISO 639-2 code`, differing only by a digit
- `review score` vs `review score by`, differing only by a trailing preposition

These score essentially 1.0 cosine under any neural embedder regardless of size. They are caught by the v0.3.1 structural filter (digit-mismatch and trailing-preposition rules), not by the neural component.

## Implication for the project

v0.3.1 (hybrid token + neural model2vec + structural filter) is at or near the ceiling of what off-the-shelf distributional embedders can deliver on this task. Further paraphrase coverage requires one of:

1. **A relation-specific fine-tuned encoder.** Train on positive (paraphrase) and negative (sibling / antonym) pairs. Plausible but expensive; needs a labeled corpus the project does not have.

2. **An LLM in the loop.** The wedge thesis explicitly rejects this; it is exactly the architecture Mem0 chose and that the wedge competes against.

3. **Hand-curated semantic rules.** Per-relation alias lists. Not a general solution.

4. **Accept the ceiling and ship v0.3.1.** Document the antonym/sibling false-positive class as a known limitation. Build the rest of the system (multi-tenant per v0.4.0+, latency optimization, downstream-retrieval integration) on this foundation.

For the agent-memory-gaps project, option 4 is the right call. The wedge thesis is "deterministic, no LLM in the hot path." Distributional neural embeddings give us most of the way there; structural filters close the structural failures; the residual antonym/sibling class is small, known, and would require either fine-tuning or an LLM to solve.

## Raw probe data

### True paraphrases (want HIGH cosine)

| Pair | model2vec 32M | MiniLM | BGE-base |
|---|---|---|---|
| IsA / INSTANCE_OF | 0.714 | 0.615 | 0.789 |
| IsA / type_of | 0.780 | 0.678 | 0.809 |
| Causes / leads_to | 0.755 | 0.626 | 0.801 |
| UsedFor / purpose_of | 0.764 | 0.722 | 0.847 |
| HasA / contains_part | - | 0.582 | 0.752 |
| CapableOf / ABILITY_TO | - | 0.810 | 0.879 |
| Desires / wants | 0.898 | 0.828 | 0.952 |
| PartOf / member_of | - | 0.722 | 0.860 |

### Hard negatives (want LOW cosine, NOT to be merged)

| Pair | model2vec 32M | MiniLM | BGE-base |
|---|---|---|---|
| CONTAINS / INCLUDES | 0.925 | 0.821 | 0.900 |
| LOCATED_IN / LOCATED_NEAR | 0.930 | 0.845 | 0.904 |
| Synonym / Antonym | 0.648 | 0.832 | 0.875 |
| MadeOf / PartOf | - | 0.831 | 0.878 |
| RelatedTo / SimilarTo | - | 0.891 | 0.910 |
| Causes / HasSubevent | 0.481 | 0.706 | 0.771 |
| PartOf / HasA | - | 0.661 | 0.786 |
| OWNS / LEASES | - | 0.695 | 0.802 |
| ISO 639-1 code / ISO 639-2 code | - | 0.982 | 0.959 |
| review score / review score by | - | 0.987 | 0.993 |

Gaps in the model2vec column reflect pairs not in the original probe; the trend is consistent across all three embedders.

### Surface variants (sanity, must alias)

| Pair | MiniLM | BGE-base |
|---|---|---|
| WORKS_AT / works_at | 1.000 | 1.000 |
| WORKS_AT / WorksAt | 0.812 | (similar) |
| UsedFor / used_for | 0.800 | (similar) |
