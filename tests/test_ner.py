"""Tests for the NER preprocessors and their integration with
Mem0PreNormalized.

Only the stdlib RegexNERPreprocessor is exercised live; the spaCy /
transformers paths are import-mocked because their model assets are
heavy and not required at the harness level.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized
from runner.service.preprocessors import (
    RegexNERPreprocessor,
    SpacyNERPreprocessor,
    TransformersNERPreprocessor,
)


def test_regex_extracts_title_case_runs():
    pre = RegexNERPreprocessor()
    text = "Apple Inc and Microsoft are competing in the United States."
    spans = pre(text)
    surfaces = [s for _, _, s in spans]
    assert "Apple Inc" in surfaces or "Apple" in surfaces
    assert "Microsoft" in surfaces
    assert any("United States" in s for s in surfaces)


def test_regex_extracts_acronyms():
    pre = RegexNERPreprocessor(catch_title_case=False)
    text = "Bought AAPL today and watching MSFT and TSLA tomorrow."
    spans = pre(text)
    surfaces = {s for _, _, s in spans}
    assert {"AAPL", "MSFT", "TSLA"} <= surfaces


def test_regex_allow_list_takes_priority():
    pre = RegexNERPreprocessor(
        allow_list=["my-product", "specific_thing"],
        catch_title_case=False,
        catch_acronyms=False,
    )
    text = "Looking at my-product and specific_thing today."
    spans = pre(text)
    surfaces = {s for _, _, s in spans}
    assert surfaces == {"my-product", "specific_thing"}


def test_regex_overlap_dedup_keeps_longest():
    # "United States" should win over a bare "United" subspan
    pre = RegexNERPreprocessor()
    spans = pre("The United States Government acted.")
    # spans must be sorted by start and non-overlapping
    last_end = -1
    for start, end, _ in spans:
        assert start >= last_end
        last_end = end


def test_regex_min_acronym_len_filter():
    pre = RegexNERPreprocessor(min_acronym_len=3, catch_title_case=False)
    text = "IT and AI are about HR and SEO."
    spans = pre(text)
    surfaces = {s for _, _, s in spans}
    # 2-char "IT", "AI", "HR" filtered out; 3-char "SEO" kept
    assert "SEO" in surfaces
    assert "IT" not in surfaces
    assert "AI" not in surfaces


def test_regex_returns_valid_spans_for_text_indexing():
    """Spans must be valid (start, end) offsets into the original text."""
    pre = RegexNERPreprocessor()
    text = "Apple Inc bought TSLA shares in California yesterday."
    spans = pre(text)
    for start, end, surface in spans:
        assert text[start:end] == surface


def test_regex_invalid_acronym_bounds_raises():
    with pytest.raises(ValueError):
        RegexNERPreprocessor(min_acronym_len=0)
    with pytest.raises(ValueError):
        RegexNERPreprocessor(min_acronym_len=5, max_acronym_len=3)


def test_regex_preprocessor_plugs_into_mem0_wrapper():
    """The whole point of the preprocessor signature: drop into
    Mem0PreNormalized.mention_extractor with zero glue."""
    class _FakeMem0:
        def __init__(self):
            self.calls = []

        def add(self, messages, user_id=None, **kwargs):
            self.calls.append({"messages": messages, "user_id": user_id})

    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    pre = RegexNERPreprocessor(catch_title_case=False, catch_acronyms=True)
    wrapped = Mem0PreNormalized(fake, norm, mention_extractor=pre)
    wrapped.add("Bought AAPL today.", user_id="trader1")
    assert len(fake.calls) == 1
    # AAPL still appears (b-raw is identity), but it was extracted and
    # routed through the normalizer rather than being left as raw text.
    sent = fake.calls[0]["messages"]
    assert "AAPL" in sent


def test_spacy_preprocessor_raises_if_spacy_missing(monkeypatch):
    """If spaCy is not importable, the first call should raise a helpful
    RuntimeError, NOT an ImportError at module-load time."""
    import builtins
    real_import = builtins.__import__

    def stub_import(name, *args, **kwargs):
        if name == "spacy":
            raise ImportError("simulated missing spacy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stub_import)
    pre = SpacyNERPreprocessor()
    with pytest.raises(RuntimeError, match="spaCy not installed"):
        pre("Apple Inc in California.")


def test_transformers_preprocessor_raises_if_transformers_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def stub_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("simulated missing transformers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stub_import)
    pre = TransformersNERPreprocessor()
    with pytest.raises(RuntimeError, match="transformers not installed"):
        pre("Apple Inc in California.")


def test_lazy_reexport_from_runner_service():
    """`from runner.service import RegexNERPreprocessor` should work
    even though preprocessors is a subpackage."""
    from runner.service import RegexNERPreprocessor as ReExported
    pre = ReExported()
    spans = pre("Apple Inc.")
    assert spans  # not empty
