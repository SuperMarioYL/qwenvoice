"""Configuration model — talker/codec GGUF paths, FFI lib path, HTTP fallback.

A QwenVoice config pins the three local artifacts that make offline Chinese
voice cloning work on consumer hardware:

* ``talker_gguf``  — ``qwen-talker-1.7b-base-Q8_0.gguf`` (the Qwen3-TTS talker).
* ``codec_gguf``   — ``qwen-tokenizer-12hz-Q8_0.gguf`` (12 Hz codec/tokenizer,
  auto-discovered as the sibling ``*tokenizer*.gguf`` next to the talker).
* ``ffi_lib_path`` — ``libgoqwen3ttscpp-*.so`` / ``*.dylib`` (the qwentts.cpp
  FFI shared library packaged by LocalAI). When the FFI lib is unavailable,
  synthesis falls back to a local vLLM-Omni HTTP server exposing the
  OpenAI-compatible ``/v1/audio/speech`` endpoint via ``http_fallback_url``.

Configs are loaded from ``~/.qwenvoice/config.yml`` (written by ``qwenvoice
init``) or overridden per-invocation by CLI flags. Everything is local — no
remote model fetch happens at synth time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_CONFIG_DIR = Path.home() / ".qwenvoice"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yml"

# Qwen3-TTS produces 24 kHz mono float32 PCM (12 Hz codec frame rate).
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_CHANNELS = 1


class QwenVoiceConfig(BaseModel):
    """Resolved configuration for a synthesis run.

    All paths are local. The model reference audio never leaves the machine —
    this is the thesis-defining constraint (see ``out_of_scope`` in the plan).
    """

    talker_gguf: str = Field(
        default="qwen-talker-1.7b-base-Q8_0.gguf",
        description="Path to the Qwen3-TTS talker GGUF (qwentts.cpp).",
    )
    codec_gguf: str = Field(
        default="qwen-tokenizer-12hz-Q8_0.gguf",
        description="Path to the 12 Hz codec/tokenizer GGUF (sibling of talker).",
    )
    ffi_lib_path: str = Field(
        default="",
        description="Path to libgoqwen3ttscpp-*.so/.dylib (qwentts.cpp FFI). Empty = auto-detect.",
    )
    http_fallback_url: str = Field(
        default="",
        description="Local vLLM-Omni OpenAI-compatible /v1/audio/speech URL (FFI fallback).",
    )
    ffmpeg_bin: str = Field(
        default="ffmpeg",
        description="ffmpeg binary path (wav→mp3 + segment concatenation).",
    )
    sample_rate: int = Field(
        default=DEFAULT_SAMPLE_RATE,
        description="PCM sample rate (Qwen3-TTS = 24 kHz).",
    )
    channels: int = Field(
        default=DEFAULT_CHANNELS,
        description="PCM channel count (mono).",
    )
    seed: int = Field(
        default=42,
        description="Per-segment fixed seed (keeps redraws voice-locked).",
    )
    max_chars_per_segment: int = Field(
        default=200,
        description="Soft ceiling for jieba sentence-boundary segmentation.",
    )

    @field_validator("sample_rate")
    @classmethod
    def _check_rate(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("sample_rate must be positive")
        return v

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(), sort_keys=False, allow_unicode=True)

    @classmethod
    def load(cls, path: Path | str | None = None) -> QwenVoiceConfig:
        """Load config from YAML, falling back to defaults when missing."""
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        if not p.exists():
            return cls()
        data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: Path | str | None = None) -> Path:
        """Persist config to YAML (used by ``qwenvoice init``)."""
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_yaml(), encoding="utf-8")
        return p


def discover_codec_gguf(talker_path: Path | str) -> str | None:
    """Auto-discover the sibling ``*tokenizer*.gguf`` next to a talker GGUF.

    Qwen3-TTS requires BOTH the talker and the codec/tokenizer GGUF to load.
    The codec ships as a sibling file whose name contains ``tokenizer``.
    """
    talker = Path(talker_path)
    search_dir = talker.parent if talker.exists() else Path(".")
    for cand in sorted(search_dir.glob("*tokenizer*.gguf")):
        return str(cand.resolve())
    return None


__all__ = [
    "QwenVoiceConfig",
    "discover_codec_gguf",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_CHANNELS",
]
