"""QwenVoice — local offline Chinese voice cloning + long-text narration.

Wraps the Qwen3-TTS GGUF inference path exposed by qwentts.cpp (packaged by
LocalAI as the FFI shared library ``libgoqwen3ttscpp``) into a one-command CLI:
lock a speaker reference + its transcript, synthesize Chinese long-text into
segmented MP3 files, and redraw any single segment without changing the locked
voice.

The voice biometric (reference audio + transcript) never leaves the machine.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
