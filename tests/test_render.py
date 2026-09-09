"""Tests for qwenvoice.render — PCM framing + segment naming.

The wav framing helper and segment-naming are pure and run everywhere. pydub's
AudioSegment.from_file shells out to ffprobe (even for an in-memory wav) and
export shells out to ffmpeg, so those tests are skipped when the binaries are
missing; CI installs ffmpeg so they run for real there.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import pytest

from qwenvoice.render import (
    PCM,
    _build_wav_float32,
    pcm_to_audio_segment,
    render_segment_with_text,
    seg_filename,
)


class TestSegFilename:
    def test_zero_padded_to_three(self) -> None:
        assert seg_filename(1) == "seg_001.mp3"
        assert seg_filename(12) == "seg_012.mp3"
        assert seg_filename(123) == "seg_123.mp3"

    def test_width_grows_past_999(self) -> None:
        assert seg_filename(1234) == "seg_1234.mp3"


class TestBuildWavFloat32:
    def _samples(self, n: int = 100) -> list[float]:
        return [i / n * 2 - 1 for i in range(n)]  # ramp -1..1

    def test_produces_valid_riff_header(self) -> None:
        s = self._samples(64)
        wav = _build_wav_float32(s, sample_rate=24000, channels=1)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        # fmt chunk size = 16, audio format = 3 (IEEE float)
        assert struct.unpack("<I", wav[16:20])[0] == 16
        assert struct.unpack("<H", wav[20:22])[0] == 3  # 32-bit float PCM
        assert wav[36:40] == b"fact"
        assert wav[48:52] == b"data"
        # data length == n samples * 4 bytes
        assert struct.unpack("<I", wav[52:56])[0] == len(s) * 4

    def test_total_length_matches(self) -> None:
        s = self._samples(128)
        wav = _build_wav_float32(s, sample_rate=24000, channels=1)
        # RIFF size field = file - 8
        assert struct.unpack("<I", wav[4:8])[0] == len(wav) - 8


class TestPcmToAudioSegment:
    def _pcm(self, n: int = 256) -> PCM:
        floats = [i / n * 2 - 1 for i in range(n)]
        raw = struct.pack("<" + "f" * len(floats), *floats)
        return PCM(samples=raw, sample_rate=24000, channels=1)

    # AudioSegment.from_file shells out to ffprobe (mediainfo_json) even for an
    # in-memory wav — without ffprobe this test crashes, so guard on it (v0.2.0
    # fix: this guard was missing and CI was red on ffmpeg-less runners).
    @pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not on PATH")
    def test_round_trip_frame_count(self) -> None:
        pcm = self._pcm(256)
        seg = pcm_to_audio_segment(pcm)
        # pydub frame_rate * frame_count_ms — check sample count roughly matches
        assert seg.frame_rate == 24000
        assert seg.channels == 1
        assert seg.frame_count() == pytest.approx(256, rel=0.05)

    def test_to_floats_round_trips(self) -> None:
        pcm = self._pcm(8)
        floats = pcm.to_floats()
        assert len(floats) == 8


class TestRenderSegmentWithText:
    # export() needs ffmpeg and from_file() needs ffprobe — pydub requires both.
    @pytest.mark.skipif(
        shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
        reason="ffmpeg/ffprobe not on PATH",
    )
    def test_writes_seg_file(self, tmp_path: Path) -> None:
        pcm = PCM(
            samples=struct.pack("<64f", *[i / 64 for i in range(64)]),
            sample_rate=24000,
            channels=1,
        )
        rendered = render_segment_with_text(pcm, seg_id=1, text="测试", output_dir=tmp_path)
        out = Path(rendered.audio_path)
        assert out.exists()
        assert out.name == "seg_001.mp3"
        assert out.stat().st_size > 0
