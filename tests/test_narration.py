"""Tests for the book/redraw orchestration (v0.3.0, plan m2/m3 wiring).

``synth_segment`` is monkeypatched to a deterministic synthetic-PCM stub, so no
model runtime is needed. Rendering runs through the real pydub/ffmpeg path —
CI installs ffmpeg, and locally the tests skip cleanly without it (same guard
contract as tests/test_render.py). What these tests verify is exactly the new
layer: orchestration, manifest state transitions, and the redraw guarantee that
only the target segment file is ever rewritten. They make no claim about voice
quality or synthesis determinism — that requires a compatible Qwen3-TTS runtime.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

import qwenvoice.cli as cli
from qwenvoice.config import QwenVoiceConfig
from qwenvoice.manifest import FULL_AUDIO_FILENAME, NarrationManifest
from qwenvoice.segment import segment_long_text
from qwenvoice.synth import PCM

runner = CliRunner()

RENDER_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_render = pytest.mark.skipif(not RENDER_AVAILABLE, reason="ffmpeg/ffprobe not on PATH")

NOVEL = (
    "这是第一句话。这是第二句话！第三句稍微长一些，包含一些额外的内容，"
    "让分段结果更有层次。最后一句收尾。"
)
REWRITE = "改写后的第二句。"


def _pcm_for(text: str) -> PCM:
    """Deterministic stand-in synthesis: waveform depends on the input text,
    so a redraw with different text produces different audio."""
    n = 480 + 96 * len(text)
    freq = 220 + (len(text) % 8) * 30
    floats = [0.4 * ((i % freq) / freq * 2 - 1) for i in range(n)]
    return PCM(samples=struct.pack("<" + "f" * n, *floats), sample_rate=24000, channels=1)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — stability check only


def _all_output(result) -> str:
    """stdout + stderr — the CLI reports errors on stderr."""
    return result.output + (result.stderr or "")


@pytest.fixture()
def narr_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake artifacts + a writable config + a stubbed synth, isolated per test."""
    (tmp_path / "mom.wav").write_bytes(b"RIFFfake-speaker-reference-audio" * 512)
    (tmp_path / "talker.gguf").write_bytes(b"fake-gguf")
    (tmp_path / "codec.gguf").write_bytes(b"fake-gguf")
    cfg = QwenVoiceConfig(
        talker_gguf=str(tmp_path / "talker.gguf"),
        codec_gguf=str(tmp_path / "codec.gguf"),
        # small soft limit so the 4-sentence fixture yields multiple segments
        max_chars_per_segment=18,
    )
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(cfg.to_yaml(), encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(cli, "synth_segment", lambda lock, text, config: _pcm_for(text))
    return tmp_path


def _run_book(env: Path, out: Path):
    novel = env / "novel.txt"
    novel.write_text(NOVEL, encoding="utf-8")
    return runner.invoke(
        cli.app,
        [
            "book",
            "--voice", str(env / "mom.wav"),
            "--ref-text", "参考录音的准确转录",
            "--file", str(novel),
            "--out", str(out),
        ],
    )


class TestBook:
    @needs_render
    def test_book_produces_segments_full_and_manifest(self, narr_env: Path) -> None:
        out = narr_env / "book"
        result = _run_book(narr_env, out)
        assert result.exit_code == 0, _all_output(result)

        manifest = NarrationManifest.load(out)
        expected = [seg.text for seg in segment_long_text(NOVEL, 18)]
        assert len(expected) > 1  # the fixture limit must actually split
        assert [seg.text for seg in manifest.segments] == expected
        assert all(seg.status == "synthesized" for seg in manifest.segments)
        for seg in manifest.segments:
            seg_file = out / seg.filename()
            assert seg_file.stat().st_size > 0
        assert (out / FULL_AUDIO_FILENAME).stat().st_size > 0
        assert manifest.full_audio == FULL_AUDIO_FILENAME

    @needs_render
    def test_book_empty_text_fails_friendly(self, narr_env: Path) -> None:
        novel = narr_env / "empty.txt"
        novel.write_text("   \n", encoding="utf-8")
        result = runner.invoke(
            cli.app,
            [
                "book",
                "--voice", str(narr_env / "mom.wav"),
                "--ref-text", "参考",
                "--file", str(novel),
                "--out", str(narr_env / "book"),
            ],
        )
        assert result.exit_code == 2
        assert "Traceback" not in _all_output(result)
        assert "segmentation failed" in _all_output(result)

    def test_book_missing_input_file(self, narr_env: Path) -> None:
        result = runner.invoke(
            cli.app,
            [
                "book",
                "--voice", str(narr_env / "mom.wav"),
                "--ref-text", "参考",
                "--file", str(narr_env / "nope.txt"),
                "--out", str(narr_env / "book"),
            ],
        )
        assert result.exit_code == 2
        assert "input file not found" in _all_output(result)


class TestRedraw:
    @needs_render
    def test_redraw_rewrites_only_target_segment(self, narr_env: Path) -> None:
        out = narr_env / "book"
        assert _run_book(narr_env, out).exit_code == 0

        before = {p.name: _md5(p) for p in out.glob("*.mp3")}
        result = runner.invoke(
            cli.app,
            ["redraw", "--book", str(out), "--seg", "2", "--text", REWRITE],
        )
        assert result.exit_code == 0, _all_output(result)

        after = {p.name: _md5(p) for p in out.glob("*.mp3")}
        changed = {name for name, digest in after.items() if digest != before.get(name)}
        assert changed == {"seg_002.mp3"}

        manifest = NarrationManifest.load(out)
        target = manifest.get_segment(2)
        assert target.text == REWRITE
        assert target.status == "redrawn"
        # neighbors keep their original text and status
        assert manifest.get_segment(1).status == "synthesized"
        assert manifest.get_segment(3).status == "synthesized"

    @needs_render
    def test_redraw_refuses_re_recorded_reference(self, narr_env: Path) -> None:
        out = narr_env / "book"
        assert _run_book(narr_env, out).exit_code == 0

        before = {p.name: _md5(p) for p in out.glob("*.mp3")}
        # re-record: same path, different bytes → the lock hash drifts
        (narr_env / "mom.wav").write_bytes(b"RIFFre-recorded-reference" * 512)
        result = runner.invoke(
            cli.app,
            ["redraw", "--book", str(out), "--seg", "2", "--text", REWRITE],
        )
        assert result.exit_code == 2
        assert "refused" in _all_output(result)
        after = {p.name: _md5(p) for p in out.glob("*.mp3")}
        assert after == before

    @needs_render
    def test_redraw_unknown_segment_id(self, narr_env: Path) -> None:
        out = narr_env / "book"
        assert _run_book(narr_env, out).exit_code == 0
        before = {p.name: _md5(p) for p in out.glob("*.mp3")}

        result = runner.invoke(
            cli.app,
            ["redraw", "--book", str(out), "--seg", "999", "--text", REWRITE],
        )
        assert result.exit_code == 2
        assert "not in manifest" in _all_output(result)
        assert {p.name: _md5(p) for p in out.glob("*.mp3")} == before

    def test_redraw_without_manifest_fails_friendly(self, narr_env: Path) -> None:
        result = runner.invoke(
            cli.app,
            ["redraw", "--book", str(narr_env / "nowhere"), "--seg", "1", "--text", REWRITE],
        )
        assert result.exit_code == 2
        assert "Traceback" not in _all_output(result)
        assert "redraw failed" in _all_output(result)

    @needs_render
    def test_redraw_empty_text_fails_friendly(self, narr_env: Path) -> None:
        out = narr_env / "book"
        assert _run_book(narr_env, out).exit_code == 0
        result = runner.invoke(
            cli.app,
            ["redraw", "--book", str(out), "--seg", "2", "--text", "   "],
        )
        assert result.exit_code == 2
        assert "--text must be non-empty" in _all_output(result)
