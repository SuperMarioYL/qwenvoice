"""VoiceLock — bind a locked speaker reference + transcript to the model artifacts.

The VoiceLock is the new primitive (see mvp_plan §2). It pins four inputs so
that synthesizing (or re-synthesizing) any segment with the same lock yields a
locked voice: the speaker reference audio, its transcript, the talker/codec
GGUF pair, and a per-segment seed. The reference biometric never leaves the
machine — the lock is a local, reproducible contract, not an uploaded profile.

``ref_hash`` is a sha256 over the audio bytes + transcript so a redraw can
verify the lock has not drifted. If you re-record the reference, the hash
changes and the manifest's voice is considered re-locked (a new lock, not a
redraw of the old one).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


def _hash_reference(ref_audio_path: Path | str, ref_text: str) -> str:
    """sha256 over audio bytes + transcript — the lock fingerprint.

    Used to detect lock drift before a redraw: if the on-disk reference audio
    or its transcript changed since the manifest was written, the hash differs
    and we refuse the redraw (it would change the voice, not just the text).
    """
    audio_bytes = Path(ref_audio_path).read_bytes()
    h = hashlib.sha256()
    h.update(b"qwenvoice-voicelock-v1\n")
    h.update(audio_bytes)
    h.update(b"\x00ref-text\x00")
    h.update(ref_text.encode("utf-8"))
    return "sha256:" + h.hexdigest()


@dataclass(slots=True)
class VoiceLock:
    """A locked speaker reference bound to the Qwen3-TTS talker/codec GGUF.

    Construct via :func:`VoiceLock.lock` so the ref_hash is always derived,
    never hand-set.
    """

    speaker_ref_path: str
    ref_text: str
    talker_gguf: str
    codec_gguf: str
    ffi_lib_path: str
    ref_hash: str
    seed: int = 42

    @classmethod
    def lock(
        cls,
        *,
        speaker_ref_path: Path | str,
        ref_text: str,
        talker_gguf: Path | str,
        codec_gguf: Path | str,
        ffi_lib_path: Path | str = "",
        seed: int = 42,
    ) -> VoiceLock:
        """Build a VoiceLock, deriving ref_hash from the reference content.

        Validates that the reference audio exists and the transcript is
        non-empty — Qwen3-TTS Base requires BOTH ref audio and its transcript
        to clone, so we fail fast here instead of inside the FFI call.
        """
        ref = Path(speaker_ref_path)
        if not ref.exists():
            raise FileNotFoundError(f"speaker reference audio not found: {ref}")
        if not ref_text.strip():
            raise ValueError("ref_text (reference transcript) must be non-empty")
        if not Path(talker_gguf).exists():
            raise FileNotFoundError(f"talker GGUF not found: {talker_gguf}")
        if not Path(codec_gguf).exists():
            raise FileNotFoundError(f"codec/tokenizer GGUF not found: {codec_gguf}")
        return cls(
            speaker_ref_path=str(Path(speaker_ref_path).resolve()),
            ref_text=ref_text.strip(),
            talker_gguf=str(Path(talker_gguf).resolve()),
            codec_gguf=str(Path(codec_gguf).resolve()),
            ffi_lib_path=str(ffi_lib_path),
            ref_hash=_hash_reference(ref, ref_text.strip()),
            seed=seed,
        )

    def verify_reference_unchanged(self) -> bool:
        """True iff the on-disk reference still matches the locked hash.

        Called before a redraw to enforce the "redraw changes text, not voice"
        contract. If the user re-recorded the reference, this returns False and
        the redraw is refused (a redraw must reuse the original lock).
        """
        try:
            current = _hash_reference(self.speaker_ref_path, self.ref_text)
        except OSError:
            return False
        return current == self.ref_hash


__all__ = ["VoiceLock"]
