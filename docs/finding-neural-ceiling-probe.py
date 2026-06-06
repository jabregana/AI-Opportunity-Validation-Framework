"""Probe script for docs/finding-neural-ceiling.md.

Compares MiniLM and BGE-base on the same paraphrase / hard-negative
sets used during the v0.2.0+ development. Run in a Python 3.12 venv
with sentence-transformers installed (PyTorch wheels not available
for Python 3.14 at this time).

  uv venv --python 3.12 .venv-3.12
  uv pip install --python .venv-3.12/bin/python sentence-transformers
  .venv-3.12/bin/python docs/finding-neural-ceiling-probe.py
"""
from __future__ import annotations
import sys
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print(
        "sentence-transformers not available in this Python. "
        "See the docstring for setup.",
        file=sys.stderr,
    )
    sys.exit(1)


TEMPLATE = "the relation type called {}"

PARAPHRASES = [
    ("IsA", "INSTANCE_OF"),
    ("IsA", "type_of"),
    ("Causes", "leads_to"),
    ("UsedFor", "purpose_of"),
    ("HasA", "contains_part"),
    ("CapableOf", "ABILITY_TO"),
    ("Desires", "wants"),
    ("PartOf", "member_of"),
]

HARD_NEGATIVES = [
    ("CONTAINS", "INCLUDES"),
    ("LOCATED_IN", "LOCATED_NEAR"),
    ("Synonym", "Antonym"),
    ("MadeOf", "PartOf"),
    ("RelatedTo", "SimilarTo"),
    ("Causes", "HasSubevent"),
    ("PartOf", "HasA"),
    ("OWNS", "LEASES"),
    ("ISO 639-1 code", "ISO 639-2 code"),
    ("review score", "review score by"),
]

MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-base-en-v1.5",
]


def cos_template(model: SentenceTransformer, a: str, b: str) -> float:
    va = model.encode(TEMPLATE.format(a), normalize_embeddings=True)
    vb = model.encode(TEMPLATE.format(b), normalize_embeddings=True)
    return float(np.dot(va, vb))


def report(model_name: str) -> dict:
    print(f"\n=== {model_name} ===")
    model = SentenceTransformer(model_name)
    para_scores = [cos_template(model, a, b) for a, b in PARAPHRASES]
    neg_scores = [cos_template(model, a, b) for a, b in HARD_NEGATIVES]

    para_median = float(np.median(para_scores))
    neg_median = float(np.median(neg_scores))
    overlap = sum(
        1 for p in para_scores for n in neg_scores if n >= p
    ) / (len(para_scores) * len(neg_scores))

    print(f"  paraphrase median:    {para_median:.3f}")
    print(f"  hard-negative median: {neg_median:.3f}")
    print(f"  overlap (hard-neg >= paraphrase): {overlap:.1%}")
    return {
        "model": model_name,
        "paraphrase_scores": dict(zip(
            [f"{a}/{b}" for a, b in PARAPHRASES], para_scores
        )),
        "hard_negative_scores": dict(zip(
            [f"{a}/{b}" for a, b in HARD_NEGATIVES], neg_scores
        )),
        "summary": {
            "paraphrase_median": para_median,
            "hard_negative_median": neg_median,
            "overlap_fraction": overlap,
        },
    }


def main():
    for m in MODELS:
        report(m)


if __name__ == "__main__":
    main()
