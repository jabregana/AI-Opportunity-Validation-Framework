"""Preprocessors that turn long-form text into entity spans the proxy
can normalize.

The proxy normalizes short surface forms (entity names, relation labels).
For long-form text (chat transcripts, articles, support tickets), an
upstream extractor is needed to identify the spans worth normalizing.

A preprocessor is any callable matching this signature:

    Callable[[str], list[tuple[int, int, str]]]

returning (start, end, surface) spans into the input text. This
matches the `mention_extractor` slot on `Mem0PreNormalized`, so any
preprocessor in this module drops straight in.
"""
from __future__ import annotations
from .coref import CorefResolver, FastcorefResolver, LLMCorefResolver
from .ner import (
    NERPreprocessor,
    RegexNERPreprocessor,
    SpacyNERPreprocessor,
    TransformersNERPreprocessor,
)

__all__ = [
    "NERPreprocessor",
    "RegexNERPreprocessor",
    "SpacyNERPreprocessor",
    "TransformersNERPreprocessor",
    "CorefResolver",
    "FastcorefResolver",
    "LLMCorefResolver",
]
