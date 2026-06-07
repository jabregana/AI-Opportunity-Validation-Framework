"""Co-reference resolution preprocessor.

The proxy normalizes entity surface forms. It does NOT resolve
co-referential expressions like "they", "the company", "both
companies", "all three". On multi-turn conversational text, those
expressions carry entity references that the proxy can't see.

The conversational benchmark (`docs/finding-conversational-llm.md`)
flagged this as a gap: the proxy lift shrinks on multi-turn because
co-reference is the LLM's job, not the proxy's. This module adds a
co-reference preprocessor that the integrator can run upstream of the
proxy so the proxy sees explicit entity mentions instead of pronouns.

Two implementations behind the same callable interface:

  1. LLMCorefResolver: uses a local Ollama LLM (or any HTTP-callable
     LLM) to rewrite pronouns and definite descriptions to their
     referents. Works well for short conversations; cost scales with
     conversation length.

  2. FastcorefResolver: wraps the fastcoref package (BERT-based,
     much faster than LLM, no network). Optional dep; raises a helpful
     RuntimeError if not installed.

Both return a REWRITTEN text where co-referential expressions have
been replaced with their resolved entity strings. The rewrite is
designed to compose cleanly with downstream NER / mention_map / proxy
normalization — the proxy then sees explicit entity mentions
everywhere.

Usage shape:

    resolver = LLMCorefResolver(model="llama3.1:8b")
    expanded_text = resolver(text)
    # expanded_text has "Apple Inc" where "they" appeared, etc.

    # Then route through the proxy:
    normalized = pre_normalize(expanded_text, alias_map)
    # ... send normalized to downstream LLM
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from typing import Protocol


class CorefResolver(Protocol):
    """Callable contract for a co-reference resolver."""

    def __call__(self, text: str) -> str: ...


OLLAMA_URL = "http://localhost:11434/api/generate"

LLM_COREF_PROMPT = (
    "You are a co-reference resolver. Rewrite the conversation below so "
    "that every pronoun and definite reference to a company, brand, or "
    "organization is replaced with the explicit name of the entity it "
    "refers to.\n\n"
    "Rules:\n"
    "- Replace 'they', 'them', 'their', 'it', 'its', 'the company', "
    "'the firm', 'both companies', 'all three' (and similar) with the "
    "explicit entity name(s).\n"
    "- Leave the rest of the text unchanged. Preserve punctuation, "
    "line breaks, and word order.\n"
    "- If you cannot determine the referent confidently, leave the "
    "original word in place.\n"
    "- Output the rewritten text ONLY. Do not add commentary, "
    "explanations, or any other text.\n\n"
    "Conversation:\n{text}\n\n"
    "Rewritten:"
)


class LLMCorefResolver:
    """LLM-based co-reference resolver via Ollama.

    Sends the entire conversation text to a local LLM with a strict
    rewrite-only prompt. Returns the LLM's rewritten text.

    Trade-offs:
      - Quality: depends on the LLM. The conversational quality
        benchmark showed even 8B models follow this kind of
        rewrite-only instruction reliably for short inputs.
      - Latency: 100ms-1s per conversation depending on model and
        text length.
      - Determinism: the LLM may produce slightly different
        rewrites across runs (mitigated by temperature=0).
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        ollama_url: str = OLLAMA_URL,
        timeout_s: float = 30.0,
    ):
        self._model = model
        self._url = ollama_url
        self._timeout = timeout_s

    def __call__(self, text: str) -> str:
        if not text or not text.strip():
            return text
        body = json.dumps({
            "model": self._model,
            "prompt": LLM_COREF_PROMPT.format(text=text),
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": max(len(text), 200)},
        }).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Ollama HTTP {e.code} from {self._url}; is the daemon "
                f"running and is model {self._model!r} pulled?"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self._url}: {e}. "
                f"Start the daemon with `ollama serve`."
            ) from e
        rewritten = payload.get("response", "").strip()
        # Strip a leading "Rewritten:" if the model echoes it.
        for prefix in ("Rewritten:", "rewritten:", "Output:"):
            if rewritten.startswith(prefix):
                rewritten = rewritten[len(prefix):].lstrip()
        return rewritten or text


class FastcorefResolver:
    """fastcoref-based co-reference resolver.

    Lazily loads the fastcoref model on first call. Requires the
    optional `[coref]` extra (`pip install fastcoref`). Much faster
    than LLM-based on long text; runs locally on CPU.
    """

    def __init__(self, model_name: str = "biu-nlp/lingmess-coref"):
        self._model_name = model_name
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            from fastcoref import FCoref  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "fastcoref not installed; install with `pip install fastcoref` "
                "or use the `[coref]` extra"
            ) from e
        self._model = FCoref(model_name_or_path=self._model_name)

    def __call__(self, text: str) -> str:
        self._ensure_loaded()
        if not text or not text.strip():
            return text
        result = self._model.predict(texts=[text])[0]
        clusters = result.get_clusters(as_strings=False)  # list[list[(start, end)]]
        cluster_strings = result.get_clusters(as_strings=True)
        # Build span -> replacement map using the longest mention per
        # cluster as the canonical replacement string. Replace shorter
        # pronominal mentions with the canonical name.
        replacements: list[tuple[int, int, str]] = []
        for spans, strings in zip(clusters, cluster_strings):
            if not spans:
                continue
            # Pick the longest string in the cluster as the canonical.
            best = max(strings, key=len)
            for (start, end), s in zip(spans, strings):
                # Only replace short (pronominal or definite) mentions.
                if len(s) <= 4 or s.lower() in {
                    "the company", "the firm", "the business",
                    "both companies", "all three", "they", "them",
                    "their", "it", "its",
                }:
                    if s != best:
                        replacements.append((start, end, best))
        if not replacements:
            return text
        # Apply right-to-left to preserve offsets.
        replacements.sort(key=lambda r: -r[0])
        out = text
        for start, end, rep in replacements:
            out = out[:start] + rep + out[end:]
        return out
