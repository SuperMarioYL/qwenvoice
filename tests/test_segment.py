"""Tests for qwenvoice.segment — Chinese sentence-boundary segmentation."""

from __future__ import annotations

import pytest

from qwenvoice.segment import (
    segment_long_text,
    segment_single,
    split_sentences,
)


class TestSplitSentences:
    def test_basic_cjk_terminators(self) -> None:
        out = split_sentences("你好世界。今天天气真好！明天见？")
        assert out == ["你好世界。", "今天天气真好！", "明天见？"]

    def test_newline_terminator(self) -> None:
        # newline splits the sentence; surrounding whitespace is stripped from
        # each emitted sentence (the bare \n is not kept in the output text).
        out = split_sentences("第一段\n第二段")
        assert out == ["第一段", "第二段"]

    def test_no_terminator_tail(self) -> None:
        out = split_sentences("完整句。没有句号的尾巴")
        assert out[0] == "完整句。"
        assert out[-1] == "没有句号的尾巴"

    def test_empty(self) -> None:
        assert split_sentences("") == []
        assert split_sentences("   \n  ") == []

    def test_ellipsis_and_semicolon(self) -> None:
        out = split_sentences("前半句；后半句…")
        assert "前半句；" in out
        assert "后半句…" in out


class TestSegmentSingle:
    def test_single_segment(self) -> None:
        segs = segment_single("你好，欢迎使用 QwenVoice。")
        assert len(segs) == 1
        assert segs[0].id == 1
        assert segs[0].text == "你好，欢迎使用 QwenVoice。"

    def test_strips_whitespace(self) -> None:
        segs = segment_single("  带空格的文本  ")
        assert segs[0].text == "带空格的文本"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            segment_single("")


class TestSegmentLongText:
    def test_short_text_one_segment(self) -> None:
        segs = segment_long_text("一句短文。")
        assert len(segs) == 1
        assert segs[0].id == 1

    def test_boundary_safety_no_mid_sentence_cut(self) -> None:
        text = "第一句话。第二句话。第三句话。第四句话。"
        segs = segment_long_text(text, max_chars_per_segment=10)
        # every segment must end on a terminator — never mid-sentence
        for s in segs:
            assert s.text.rstrip()[-1] in "。！？!?；;\n…"

    def test_ids_are_contiguous_and_one_indexed(self) -> None:
        text = "甲。乙。丙。丁。戊。"
        segs = segment_long_text(text, max_chars_per_segment=5)
        assert [s.id for s in segs] == list(range(1, len(segs) + 1))

    def test_overlong_sentence_emitted_intact(self) -> None:
        long_sent = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常长的单句。" * 3
        segs = segment_long_text(long_sent, max_chars_per_segment=20)
        # the overlong sentence is its own segment, not mid-cut
        assert any(len(s.text) > 20 for s in segs)
        # and it still ends with its terminator
        assert segs[-1].text.rstrip()[-1] in "。！？"

    def test_concatenation_reconstructs_source_text_order(self) -> None:
        text = "第一句。第二句。第三句。第四句。"
        segs = segment_long_text(text, max_chars_per_segment=10)
        rejoined = "".join(s.text for s in segs)
        # every source sentence appears, in order, across the segments
        for sent in ("第一句。", "第二句。", "第三句。", "第四句。"):
            assert sent in rejoined

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            segment_long_text("")


class TestConsecutiveTerminators:
    """v0.2.0 regression — terminator runs (？！！！。。。) must survive intact.

    The v0.1.0 regex matched exactly one terminator per sentence and derived
    the trailing fragment from the length of the concatenated matches, so runs
    were skipped and the tail slice landed mid-text (silent character loss and
    spurious punctuation-only fragments).
    """

    @pytest.mark.parametrize(
        "text",
        [
            "怎么会这样？！真的吗。",
            "太好了！！我们走吧。",
            "等等。。。你说什么？",
            "什么？！",
        ],
    )
    def test_no_loss_no_spurious_fragments(self, text: str) -> None:
        sents = split_sentences(text)
        # every input character survives, in order — no loss, no reordering
        assert "".join(sents) == text
        # no fragment is bare punctuation (the old spurious '。' / '！' tails)
        for s in sents:
            assert any(ch not in "。！？!?；;\n…" for ch in s), f"spurious fragment {s!r}"

    def test_terminator_run_stays_with_its_sentence(self) -> None:
        assert split_sentences("怎么会这样？！真的吗。") == ["怎么会这样？！", "真的吗。"]
        assert split_sentences("等等。。。你说什么？") == ["等等。。。", "你说什么？"]

    def test_long_text_emits_no_garbage_segments(self) -> None:
        text = "太好了！！我们出发吧。真的吗？！"
        segs = segment_long_text(text, max_chars_per_segment=10)
        assert [s.text for s in segs] == ["太好了！！", "我们出发吧。", "真的吗？！"]
