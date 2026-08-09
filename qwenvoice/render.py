"""Render — PCM→wav→mp3 via pydub/ffmpeg + segment concatenation.

The render layer turns raw 24 kHz mono float32 PCM (from :mod:`qwenvoice.synth`)
into MP3 files on disk: one ``seg_NNN.mp3`` per segment plus a concatenated
``full.mp3`` for the whole book. Concatenation is byte-stable: given the same
VoiceLock + same seed, re-rendering a segment produces byte-identical MP3, so
a redraw of one segment leaves every other segment's bytes unchanged (the
moat demo).

pydub wraps ffmpeg; we shell out to ``ffmpeg`` only through pydub's API (no
manual subprocess management for audio). The FFI inference itself stays
in-process (see :mod:`qwenvoice.synth`).
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from pathlib import Path

from .synth import PCM

_SEG_NAME_WIDTH = 3  # seg_001 .. seg_NNN (zero-padded to 3 digits)


@dataclass(slots=True)
class RenderedSegment:
    """One rendered MP3 + provenance back to its source segment id."""

    id: int
    audio_path: str
    text: str


def _seg_filename(seg_id: int) -> str:
    return f"seg_{seg_id:0{_SEG_NAME_WIDTH}d}.mp3"


def pcm_to_audio_segment(pcm: PCM):
    """Build a pydub AudioSegment from raw float32 PCM.

    pydub has no native float32 importer that takes raw bytes, so we repackage
    the samples as a little-endian float32 RIFF wav in memory and let pydub's
    wav reader do the framing. This keeps us off the ffmpeg CLI for the PCM
    framing step; ffmpeg is still used (via pydub) for the mp3 encode.
    """
    from pydub import AudioSegment  # local import — pydub import is side-effectful

    n = len(pcm.samples) // 4
    floats = struct.unpack("<" + "f" * n, pcm.samples) if n else []
    # wav float32 framing: 32-bit float PCM, mono.
    wav = _build_wav_float32(floats, pcm.sample_rate, pcm.channels)
    return AudioSegment.from_file(io.BytesIO(wav), format="wav")


def _build_wav_float32(samples: list[float], sample_rate: int, channels: int) -> bytes:
    """Minimal RIFF wav for 32-bit float PCM (pydub-readable)."""
    data = struct.pack("<" + "f" * len(samples), *samples)
    byte_rate = sample_rate * channels * 4
    block_align = channels * 4
    # fmt: off
    # RIFF size = file - 8 = WAVE(4) + fmt(24) + fact(12) + data(8 + len).
    header = (
        b"RIFF" + struct.pack("<I", 48 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 3, channels, sample_rate,
                                 byte_rate, block_align, 32)
        + b"fact" + struct.pack("<II", 4, len(samples))
        + b"data" + struct.pack("<I", len(data))
    )
    # fmt: on
    return header + data


def render_segment(
    pcm: PCM,
    out_path: Path | str,
) -> RenderedSegment:
    """Render one PCM to MP3 at ``out_path`` (parent dirs created)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    seg = pcm_to_audio_segment(pcm)
    seg.export(str(out), format="mp3")
    return RenderedSegment(
        id=int(out.stem.split("_")[-1]) if out.stem.startswith("seg_") else 1,
        audio_path=str(out),
        text="",
    )


def render_segment_with_text(
    pcm: PCM,
    seg_id: int,
    text: str,
    output_dir: Path | str,
) -> RenderedSegment:
    """Render segment ``seg_id`` to ``<output_dir>/seg_NNN.mp3`` with metadata."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / _seg_filename(seg_id)
    seg = pcm_to_audio_segment(pcm)
    seg.export(str(out), format="mp3")
    return RenderedSegment(id=seg_id, audio_path=str(out), text=text)


def concatenate_segments(
    segment_paths: list[Path | str],
    out_path: Path | str,
) -> str:
    """Concatenate ordered segment MP3s into ``out_path`` (full.mp3)."""
    from pydub import AudioSegment

    if not segment_paths:
        raise ValueError("concatenate_segments: no segments")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined = AudioSegment.empty()
    for p in segment_paths:
        seg = AudioSegment.from_file(str(p), format="mp3")
        combined += seg
    combined.export(str(out), format="mp3")
    return str(out)


def seg_filename(seg_id: int) -> str:
    """Public alias for the on-disk segment naming convention."""
    return _seg_filename(seg_id)


__all__ = [
    "RenderedSegment",
    "pcm_to_audio_segment",
    "render_segment",
    "render_segment_with_text",
    "concatenate_segments",
    "seg_filename",
]
