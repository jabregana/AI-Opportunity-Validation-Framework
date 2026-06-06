"""Named-entity recognition preprocessors that produce mention spans.

Each preprocessor returns a list of (start, end, surface) tuples. The
proxy then normalizes each surface form via the EntityNormalizer and
the integrating wrapper rewrites the input text accordingly.

Three implementations:

  1. RegexNERPreprocessor: pure-stdlib pattern-based extractor. Picks
     up Title Case multi-word sequences, all-caps acronyms (2-6
     chars), and an optional configurable allow-list of literal
     mentions. Good enough for narrow domains (tickers, product
     names, codes) and as a baseline when external NER is not
     available.

  2. SpacyNERPreprocessor: wraps spaCy's `nlp.ents`. Requires the
     optional `[ner]` extra (`pip install spacy` + a model like
     `en_core_web_sm`). Lazily loads the model on first use.

  3. TransformersNERPreprocessor: wraps a HuggingFace transformers
     pipeline (`pipeline("ner", aggregation_strategy="simple")`).
     Requires `transformers` + `torch`. Lazily loaded.

None of the model-backed implementations are required at import time.
Imports are guarded so the rest of the project keeps stdlib-only
defaults.

The preprocessor signature exactly matches
`Mem0PreNormalized(mention_extractor=...)`, so any of these can be
dropped into an existing wrapper without changes elsewhere.
"""
from __future__ import annotations
import re
from typing import Iterable, Protocol


class NERPreprocessor(Protocol):
    """Callable contract for a mention extractor."""

    def __call__(self, text: str) -> list[tuple[int, int, str]]: ...


# Two regexes used by RegexNERPreprocessor. The Title Case run is the
# load-bearing pattern; the acronym pattern is a deliberately narrow
# 2-6 character all-caps run to catch tickers and codes without
# matching every uppercase word in a shout.
_TITLE_RUN = re.compile(
    r"(?:[A-Z][a-z]+(?:\s+(?:of|the|de|von|van))?\s+)*[A-Z][a-z]+(?:\s+Inc\.?|\s+Corp\.?|\s+Co\.?|\s+Ltd\.?)?"
)
_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")


class RegexNERPreprocessor:
    """Pure-stdlib pattern-based mention extractor.

    Picks up:
      - Title Case multi-word sequences (e.g. "Apple Inc", "United
        States", "Bank of America"), with optional corporate suffixes.
      - All-caps tokens 2-6 chars long (tickers, country codes, ISO
        codes: AAPL, USA, ISO).
      - Any literal in `allow_list`, matched as whole words. Use this
        for domain-specific aliases the regex would miss
        (e.g. lowercase product codes, mixed-case product names).

    The result is sorted by start offset and overlap-deduplicated:
    longer spans win over shorter spans that start inside them. The
    allow-list takes priority over the regex matches when both cover
    the same characters.

    Limitations: this is heuristic, not statistical. It will miss
    lowercase brand names, will pick up false positives on Title Case
    that happens to start a sentence, and does not disambiguate
    homographs. Use a model-backed preprocessor for production
    long-form text.
    """

    def __init__(
        self,
        allow_list: Iterable[str] | None = None,
        catch_title_case: bool = True,
        catch_acronyms: bool = True,
        min_acronym_len: int = 2,
        max_acronym_len: int = 6,
    ):
        if min_acronym_len < 1 or max_acronym_len < min_acronym_len:
            raise ValueError(
                f"invalid acronym bounds: {min_acronym_len}..{max_acronym_len}"
            )
        self._allow = list(allow_list) if allow_list else []
        self._catch_title = catch_title_case
        self._catch_acronyms = catch_acronyms
        if catch_acronyms:
            self._acronym = re.compile(
                rf"\b[A-Z]{{{min_acronym_len},{max_acronym_len}}}\b"
            )

    def __call__(self, text: str) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str, int]] = []  # (start, end, surface, priority)

        # priority 2: allow-list literals (highest)
        for literal in self._allow:
            if not literal:
                continue
            pattern = re.compile(rf"\b{re.escape(literal)}\b")
            for m in pattern.finditer(text):
                spans.append((m.start(), m.end(), m.group(0), 2))

        # priority 1: title case runs
        if self._catch_title:
            for m in _TITLE_RUN.finditer(text):
                surface = m.group(0).strip()
                if surface:
                    spans.append((m.start(), m.start() + len(surface), surface, 1))

        # priority 0: acronyms (lowest, often subsumed by allow-list)
        if self._catch_acronyms:
            for m in self._acronym.finditer(text):
                spans.append((m.start(), m.end(), m.group(0), 0))

        # Overlap dedup: sort by start, then by (-priority, -length) so
        # higher-priority/longer spans win when starts tie.
        spans.sort(key=lambda s: (s[0], -s[3], -(s[1] - s[0])))
        out: list[tuple[int, int, str]] = []
        last_end = -1
        for start, end, surface, _prio in spans:
            if start < last_end:
                continue  # overlapping with an already-accepted span
            out.append((start, end, surface))
            last_end = end
        return out


class SpacyNERPreprocessor:
    """spaCy-backed mention extractor.

    Lazily loads the model on first call. Accepts any spaCy entity
    label set; the default keeps the model's named entities verbatim
    (PERSON, ORG, GPE, PRODUCT, etc.) and filters out value entities
    (DATE, TIME, MONEY, PERCENT, ORDINAL, CARDINAL) which are rarely
    what a normalization layer is supposed to canonicalize.
    """

    DEFAULT_KEEP_LABELS = frozenset(
        {"PERSON", "ORG", "GPE", "LOC", "PRODUCT", "WORK_OF_ART",
         "EVENT", "LAW", "LANGUAGE", "NORP", "FAC"}
    )

    def __init__(
        self,
        model_name: str = "en_core_web_sm",
        keep_labels: Iterable[str] | None = None,
    ):
        self._model_name = model_name
        self._keep_labels = (
            frozenset(keep_labels) if keep_labels is not None
            else self.DEFAULT_KEEP_LABELS
        )
        self._nlp = None

    def _ensure_loaded(self):
        if self._nlp is not None:
            return
        try:
            import spacy
        except ImportError as e:
            raise RuntimeError(
                "spaCy not installed; install with `pip install spacy` "
                "and the model with `python -m spacy download "
                f"{self._model_name}`"
            ) from e
        try:
            self._nlp = spacy.load(self._model_name)
        except OSError as e:
            raise RuntimeError(
                f"spaCy model {self._model_name!r} not available. "
                f"Install with `python -m spacy download {self._model_name}`"
            ) from e

    def __call__(self, text: str) -> list[tuple[int, int, str]]:
        self._ensure_loaded()
        doc = self._nlp(text)
        out: list[tuple[int, int, str]] = []
        for ent in doc.ents:
            if ent.label_ not in self._keep_labels:
                continue
            out.append((ent.start_char, ent.end_char, ent.text))
        out.sort(key=lambda s: s[0])
        return out


class TransformersNERPreprocessor:
    """HuggingFace transformers NER pipeline.

    Lazily constructs the pipeline on first call. The default model
    (dslim/bert-base-NER) is a small fine-tuned BERT that emits
    PER / ORG / LOC / MISC labels. Aggregation strategy "simple"
    merges subword tokens into whole-entity spans.
    """

    DEFAULT_KEEP_LABELS = frozenset({"PER", "ORG", "LOC", "MISC"})

    def __init__(
        self,
        model_name: str = "dslim/bert-base-NER",
        keep_labels: Iterable[str] | None = None,
        device: int = -1,
    ):
        self._model_name = model_name
        self._keep_labels = (
            frozenset(keep_labels) if keep_labels is not None
            else self.DEFAULT_KEEP_LABELS
        )
        self._device = device
        self._pipeline = None

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return
        try:
            from transformers import pipeline as hf_pipeline
        except ImportError as e:
            raise RuntimeError(
                "transformers not installed; install with "
                "`pip install transformers torch`"
            ) from e
        self._pipeline = hf_pipeline(
            "ner",
            model=self._model_name,
            aggregation_strategy="simple",
            device=self._device,
        )

    def __call__(self, text: str) -> list[tuple[int, int, str]]:
        self._ensure_loaded()
        raw = self._pipeline(text)
        out: list[tuple[int, int, str]] = []
        for span in raw:
            label = span.get("entity_group") or span.get("entity")
            if label and label.upper() not in self._keep_labels:
                continue
            start = int(span["start"])
            end = int(span["end"])
            out.append((start, end, text[start:end]))
        out.sort(key=lambda s: s[0])
        return out
