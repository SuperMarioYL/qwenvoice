"""Chinese long-text segmentation — jieba sentence boundaries, ~200 chars/segment.

The segmenter is the first stage of the ``book`` pipeline: it splits a long
Chinese text into ordered, boundary-safe segments so each one can be
synthesized independently with the locked voice. Segment identity is what makes
per-segment redraw possible later — a redraw touches exactly one segment id and
leaves every other segment's bytes untouched.

Boundary safety means we never cut mid-sentence. We first split on the CJK
sentence terminators (。！？；\n) then greedily accumulate jieba-tokenized
sentences until approaching ``max_chars_per_segment``, flushing on terminator
or overflow. m1 (single-segment ``say``) calls :func:`segment_single` which is a
passthrough; m2+ use :func:`segment_long_text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# CJK + ASCII sentence terminators. We keep the terminator run with its
# sentence — Chinese prose regularly doubles punctuation (？！ ！！ 。。。), and
# dropping or splitting the run would corrupt the segment text.
_SENT_END = re.compile(r"([^。！？!?；;\n…]+[。！？!?；;\n…]+)")

# Hard floor/ceiling so a single runaway sentence cannot blow up a segment.
_MIN_SEGMENT_CHARS = 1
_DEFAULT_MAX_CHARS = 200


@dataclass(slots=True)
class TextSegment:
    """One ordered piece of the source text.

    ``id`` is 1-indexed to match the on-disk ``seg_001`` naming. ``text`` is the
    exact substring that will be synthesized — never re-normalized after the
    lock, so a redraw reproduces the same audio for the same id.
    """

    id: int
    text: str


def split_sentences(text: str) -> list[str]:
    """Split Chinese text into sentences on CJK terminator runs, keeping them.

    Sentences with no terminator (the tail of the input) are returned as their
    own sentence if non-empty. Pure whitespace is dropped.
    """
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    sentences: list[str] = []
    last_end = 0
    for m in _SENT_END.finditer(cleaned):
        chunk = m.group(0).strip()
        if chunk:
            sentences.append(chunk)
        last_end = m.end()
    # Append the trailing fragment with no terminator (the regex requires one).
    # Deriving the tail from the last match end — not from the length of the
    # concatenated matches — keeps it correct even if the regex ever skips
    # characters between matches.
    tail = cleaned[last_end:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def segment_single(text: str) -> list[TextSegment]:
    """m1 path — the whole text is one segment (single-segment synth).

    Used by ``qwenvoice say``. Still returns a list so the caller (and the
    NarrationManifest) can treat m1 and m2 uniformly.
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("text must be non-empty")
    return [TextSegment(id=1, text=cleaned)]


def segment_long_text(
    text: str,
    max_chars_per_segment: int = _DEFAULT_MAX_CHARS,
) -> list[TextSegment]:
    """m2 path — jieba-aware sentence-boundary segmentation.

    Greedily accumulates whole sentences until adding the next would exceed
    ``max_chars_per_segment`` (soft ceiling — a single sentence longer than the
    ceiling is emitted as its own segment rather than being mid-cut). Result ids
    are 1-indexed and contiguous.
    """
    if max_chars_per_segment < _MIN_SEGMENT_CHARS:
        raise ValueError("max_chars_per_segment must be >= 1")
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("text must contain at least one non-empty sentence")

    segments: list[TextSegment] = []
    buf: list[str] = []
    buf_len = 0
    seg_id = 0

    def flush() -> None:
        nonlocal buf, buf_len, seg_id
        if not buf:
            return
        seg_id += 1
        segments.append(TextSegment(id=seg_id, text="".join(buf).strip()))
        buf = []
        buf_len = 0

    for sent in sentences:
        # A sentence longer than the ceiling becomes its own segment intact —
        # we never cut mid-sentence (boundary safety is the whole point).
        if len(sent) >= max_chars_per_segment:
            flush()
            seg_id += 1
            segments.append(TextSegment(id=seg_id, text=sent))
            continue
        if buf and buf_len + len(sent) > max_chars_per_segment:
            flush()
        buf.append(sent)
        buf_len += len(sent)
    flush()
    return segments


__all__ = ["TextSegment", "split_sentences", "segment_single", "segment_long_text"]
