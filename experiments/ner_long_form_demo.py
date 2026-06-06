"""End-to-end demo: long-form text -> NER preprocessor -> EntityNormalizer
-> canonicalized text.

This is what v0.5.6 unlocks: the proxy was previously a no-op on
long-form text because it had no way to identify the spans to
normalize. With a preprocessor in front, integrators can drop the
proxy into any pipeline that handles chat transcripts, articles, or
support tickets.

Run:
  .venv/bin/python experiments/ner_long_form_demo.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.service import EntityNormalizer
from runner.service.preprocessors import RegexNERPreprocessor


SAMPLE_TEXT = """\
On Monday morning the trader bought 100 shares of AAPL and 50 shares of
MSFT. He noted that Apple Inc had just released their Q4 results and
Microsoft Corp was about to. Later in the day he sold the AAPL position
and rotated into TSLA, taking some profits on Apple Inc and waiting for
Microsoft Corporation earnings on Thursday.
"""


def main():
    print("Original text:")
    print(SAMPLE_TEXT)

    # The proxy uses identity matching here; in production you would
    # use one of the embedding variants (v0.3.1, v0.5.5-ann, etc.) and
    # an alias map so that "AAPL", "Apple Inc", and "Apple Inc."
    # canonicalize to the same entity.
    norm = EntityNormalizer("b-raw-identity")

    pre = RegexNERPreprocessor(
        allow_list=["AAPL", "MSFT", "TSLA"],
        catch_title_case=True,
        catch_acronyms=True,
    )

    spans = pre(SAMPLE_TEXT)
    print(f"Extracted {len(spans)} entity spans:")
    for start, end, surface in spans:
        canonical = norm.normalize(surface)
        marker = " (canonicalized)" if canonical != surface else ""
        print(f"  [{start:4d}..{end:4d}] {surface!r:24} -> {canonical!r}{marker}")

    # Rewrite the text right-to-left so offsets stay valid as we mutate.
    out = SAMPLE_TEXT
    for start, end, surface in sorted(spans, key=lambda s: -s[0]):
        canonical = norm.normalize(surface)
        out = out[:start] + canonical + out[end:]
    print("\nText after normalization (identity for this demo):")
    print(out)

    # The same wiring works with Mem0PreNormalized; uncomment to test
    # against a live Mem0 backend:
    #
    # from mem0 import Memory
    # from runner.service.integrations import Mem0PreNormalized
    # wrapped = Mem0PreNormalized(Memory(), norm, mention_extractor=pre)
    # wrapped.add(SAMPLE_TEXT, user_id="trader1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
