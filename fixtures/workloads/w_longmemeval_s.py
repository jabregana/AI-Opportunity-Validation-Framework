"""W-LONGMEMEVAL-S — LongMemEval-S benchmark adapted for clustering eval.

Adapted from the LongMemEval-S QA-over-long-context benchmark
(Xu et al., 2024). Each LongMemEval entry contributes TWO workload
entries that should cluster together:

  (source="haystack",  input=question_text, oracle=question_id)
  (source="answer",    input=answer_text,   oracle=question_id)

A working variant should recognize that a question and its answer
reference the same underlying entity / fact, and cluster them under
the same canonical. The B-cubed F1 metric then measures cross-source
clustering quality on real conversational data.

This is the "lite" real-data UC-4.7. It uses real text from the
LongMemEval-S benchmark but reformulates retrieval as clustering.
A full retrieval-system UC-4.7 (proxy interposed during haystack
ingestion, retrieval F1@10 scored against the answer key) is
deferred. See docs/longmemeval-integration-plan.md.

The dataset must be downloaded once via huggingface_hub:

  from huggingface_hub import hf_hub_download
  hf_hub_download(
      repo_id="xiaowu0162/LongMemEval",
      repo_type="dataset",
      filename="longmemeval_s",
  )
"""
from __future__ import annotations
import json
from pathlib import Path

# Default cache location (resolved at load time).
_HF_CACHE = (
    Path.home() / ".cache" / "huggingface" / "hub"
    / "datasets--xiaowu0162--LongMemEval" / "snapshots"
)


def _find_dataset_file() -> Path | None:
    """Search the HF cache for the longmemeval_s file."""
    if not _HF_CACHE.exists():
        return None
    for snapshot_dir in _HF_CACHE.iterdir():
        candidate = snapshot_dir / "longmemeval_s"
        if candidate.exists():
            return candidate
    return None


def load():
    from . import WorkloadEntry

    dataset_path = _find_dataset_file()
    if dataset_path is None:
        raise FileNotFoundError(
            "LongMemEval-S not in HF cache. Download via:\n"
            "  from huggingface_hub import hf_hub_download\n"
            '  hf_hub_download(repo_id="xiaowu0162/LongMemEval", '
            'repo_type="dataset", filename="longmemeval_s")'
        )

    data = json.loads(dataset_path.read_text())
    entries: list[WorkloadEntry] = []
    for item in data:
        qid = item["question_id"]
        question = item["question"].strip()
        answer = str(item["answer"]).strip()
        if not question or not answer:
            continue
        entries.append(WorkloadEntry("haystack", question, qid))
        entries.append(WorkloadEntry("answer", answer, qid))
    return entries
