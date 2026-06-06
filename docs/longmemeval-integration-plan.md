# LongMemEval-S Integration Plan

Status: dataset downloaded, integration deferred.

## What LongMemEval-S is

A QA-over-long-context benchmark from Xu et al. (2024). Downloaded via
the Hugging Face Hub:

```python
from huggingface_hub import hf_hub_download
path = hf_hub_download(
    repo_id="xiaowu0162/LongMemEval",
    repo_type="dataset",
    filename="longmemeval_s",
)
```

Cached at `~/.cache/huggingface/hub/datasets--xiaowu0162--LongMemEval/...`.

Format: JSON array, each entry is a question with the dialogue haystack
that should contain the answer. Roughly 500 entries, 278MB on disk.

Each entry has:
- `question_id`, `question_type`, `question` (the question text)
- `answer` (the ground-truth answer string)
- `question_date`, `haystack_dates` (timestamps)
- `haystack_sessions` (multi-turn dialogues; the memory context)
- `haystack_session_ids`, `answer_session_ids`

## Why this is not a drop-in workload

The proxy's existing UC-4.1 / UC-4.4 / UC-4.7 modes operate on
`(source_id, surface_form, oracle_canonical)` tuples. LongMemEval-S
operates on `(question, dialogue_haystack, answer)` tuples. The
adaptation is not trivial because:

1. **Memory items are turn-level, not entity-level.** A LongMemEval
   "memory" is a turn of dialogue, often a full sentence or paragraph.
   The proxy aligns short relation/entity surface forms. Going from
   dialogue turns to surface-form mentions requires either NER or a
   chunking step.

2. **Retrieval is the metric, not clustering.** UC-4.7 in the spec is
   "downstream retrieval F1@10 with and without the proxy interposed."
   Building this requires standing up a retrieval system (vector store,
   re-ranker, query encoder) and scoring against the answer key. The
   proxy's role is to canonicalize entity mentions during ingestion;
   retrieval F1 measures whether the canonical store improves answer
   recall.

3. **Source attribution is not in the dataset.** All haystacks come
   from a single user/source. Multi-tenant variants (v0.4.0+) cannot
   be evaluated on this data unless source_id is synthesized.

## Real UC-4.7 integration path

A real LongMemEval-S UC-4.7 needs:

1. **Mention extractor.** Either:
   - NER pipeline (spaCy or a small transformer) to pull entity
     mentions from each turn.
   - Coreference resolver to link mentions across turns.
   - Or: hand-curated entity tags in the original dataset (does not
     appear to be present).

2. **Workload generator.** For each LongMemEval entry, produce a
   sequence of `WorkloadEntry(source_id, mention_surface, oracle_canonical)`
   tuples where `oracle_canonical` is derived from the answer entity.

3. **Retrieval scorer.** Given the proxy-built canonical store, run
   each question's lookup and measure whether the proxy's canonical
   for the question's mention matches the answer's canonical. Score
   as Δ retrieval F1@10 vs no-proxy baseline.

4. **Source synthesis (for multi-tenant variants).** Partition
   haystacks into pseudo-sources (e.g., by topic cluster) so multi-
   tenant variants get meaningful source_id signal.

## Workload stub

Registered in `fixtures/workloads/__init__.py` as `W-LONGMEMEVAL-S`
with `status: stub`. The loader raises NotImplementedError pointing
at this doc.

Effort estimate for full integration: roughly one focused session
(2-4 hours) for the basic version (single-source, simple NER, F1@10
scorer); longer for the multi-tenant variant.
