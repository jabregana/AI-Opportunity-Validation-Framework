"""Tests for the co-reference resolver preprocessors.

LLMCorefResolver is exercised against a mocked Ollama endpoint so the
test suite stays fast and offline. FastcorefResolver is tested with
import-mocking (we don't require fastcoref + its model weights for
the harness suite).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.service.preprocessors import (
    FastcorefResolver,
    LLMCorefResolver,
)


class _FakeOllamaResponse:
    """Stand-in for an Ollama HTTP response with the given JSON body."""

    def __init__(self, text: str):
        self._body = json.dumps({"response": text}).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_urlopen(monkeypatch, response_text: str):
    """Patch urllib.request.urlopen used inside the coref module."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _FakeOllamaResponse(response_text)

    from runner.service.preprocessors import coref as coref_module
    monkeypatch.setattr(coref_module.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_llm_coref_returns_empty_for_empty_input():
    pre = LLMCorefResolver()
    assert pre("") == ""
    assert pre("   ") == "   "


def test_llm_coref_returns_rewritten_text(monkeypatch):
    captured = _patch_urlopen(
        monkeypatch,
        "Apple Inc had a strong quarter. Apple Inc reported revenue growth.",
    )
    pre = LLMCorefResolver(model="llama3.1:8b")
    out = pre("Apple Inc had a strong quarter. They reported revenue growth.")
    assert "Apple Inc" in out
    assert "They" not in out
    # Verify the request body had the model and prompt
    sent = json.loads(captured["body"].decode("utf-8"))
    assert sent["model"] == "llama3.1:8b"
    assert "co-reference resolver" in sent["prompt"]


def test_llm_coref_strips_leading_rewritten_label(monkeypatch):
    """Some models prefix the output with 'Rewritten:'; the wrapper
    should strip that."""
    _patch_urlopen(monkeypatch, "Rewritten: Apple Inc had a strong quarter.")
    pre = LLMCorefResolver()
    out = pre("Apple Inc had a strong quarter.")
    assert out == "Apple Inc had a strong quarter."


def test_llm_coref_falls_back_to_input_on_empty_response(monkeypatch):
    _patch_urlopen(monkeypatch, "")
    pre = LLMCorefResolver()
    out = pre("Some input text.")
    assert out == "Some input text."


def test_llm_coref_raises_helpful_error_on_url_failure(monkeypatch):
    """If Ollama is unreachable, the wrapper raises RuntimeError with
    a hint, not a bare urllib URLError."""
    import urllib.error
    from runner.service.preprocessors import coref as coref_module

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(coref_module.urllib.request, "urlopen", fake_urlopen)
    pre = LLMCorefResolver()
    with pytest.raises(RuntimeError, match="Could not reach Ollama"):
        pre("any text")


def test_fastcoref_raises_if_package_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def stub_import(name, *args, **kwargs):
        if name == "fastcoref":
            raise ImportError("simulated missing fastcoref")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stub_import)
    pre = FastcorefResolver()
    with pytest.raises(RuntimeError, match="fastcoref not installed"):
        pre("Some text.")
