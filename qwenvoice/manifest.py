"""NarrationManifest — the core primitive binding a VoiceLock to ordered segments.

The manifest is the single source of truth for a narration project: it pins the
locked voice (so a redraw knows which lock to reuse) and the ordered list of
segments with their on-disk MP3 paths and status. It lives at
``<output_dir>/manifest.json`` and is what makes per-segment redraw enforceable:
``redraw`` re-reads the manifest, re-synthesizes exactly one segment id with the
existing VoiceLock, and overwrites only that segment's MP3 — every other
segment's bytes stay byte-identical.

This is the moat. GPT-SoVITS has no in-place per-segment redraw contract; cloud
TTS has no offline voice lock. The manifest is the artifact that makes the
"redraw segment 12, voice unchanged, others untouched" demo reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .render import seg_filename
from .voice import VoiceLock

MANIFEST_FILENAME = "manifest.json"
FULL_AUDIO_FILENAME = "full.mp3"

SegStatus = Literal["pending", "synthesized", "redrawn"]


class Segment(BaseModel):
    """One ordered piece of the source text and its rendered audio path."""

    id: int = Field(description="1-indexed segment id matching seg_NNN.mp3.")
    text: str = Field(description="Exact text for this segment (never re-normalized).")
    audio_path: str = Field(default="", description="Path to seg_NNN.mp3 (relative to output_dir).")
    status: SegStatus = Field(default="pending")

    def filename(self) -> str:
        return seg_filename(self.id)


class VoiceLockModel(BaseModel):
    """Serializable form of a VoiceLock for the manifest."""

    speaker_ref_path: str
    ref_text: str
    talker_gguf: str
    codec_gguf: str
    ffi_lib_path: str
    ref_hash: str
    seed: int


class NarrationManifest(BaseModel):
    """A locked voice + ordered segments + their rendered MP3s.

    Written by ``qwenvoice book`` and read/mutated by ``qwenvoice redraw``. The
    VoiceLock is frozen at write time; a redraw reuses it verbatim (verified via
    ``ref_hash``) so the voice never drifts across redraws.
    """

    voice: VoiceLockModel
    segments: list[Segment] = Field(default_factory=list)
    output_dir: str = ""
    full_audio: str = ""

    @classmethod
    def from_lock(
        cls,
        lock: VoiceLock,
        *,
        segment_texts: list[str],
        output_dir: Path | str,
    ) -> NarrationManifest:
        """Build a fresh manifest from a VoiceLock + ordered segment texts."""
        out = str(output_dir)
        segs = [
            Segment(id=i + 1, text=t, audio_path=seg_filename(i + 1), status="pending")
            for i, t in enumerate(segment_texts)
        ]
        return cls(
            voice=VoiceLockModel(
                speaker_ref_path=lock.speaker_ref_path,
                ref_text=lock.ref_text,
                talker_gguf=lock.talker_gguf,
                codec_gguf=lock.codec_gguf,
                ffi_lib_path=lock.ffi_lib_path,
                ref_hash=lock.ref_hash,
                seed=lock.seed,
            ),
            segments=segs,
            output_dir=out,
            full_audio=FULL_AUDIO_FILENAME,
        )

    # -- persistence --------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return Path(self.output_dir) / MANIFEST_FILENAME

    def write(self) -> Path:
        """Persist manifest.json into output_dir (created if missing)."""
        p = self.manifest_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, output_dir: Path | str) -> NarrationManifest:
        """Read manifest.json from an existing narration dir."""
        p = Path(output_dir) / MANIFEST_FILENAME
        if not p.exists():
            raise FileNotFoundError(f"no manifest.json in {output_dir}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    # -- redraw helpers -----------------------------------------------------
    def get_segment(self, seg_id: int) -> Segment:
        for s in self.segments:
            if s.id == seg_id:
                return s
        raise KeyError(f"segment id {seg_id} not in manifest")

    def mark_redrawn(self, seg_id: int, new_text: str) -> Segment:
        """Update one segment's text + status in place (used by ``redraw``)."""
        seg = self.get_segment(seg_id)
        seg.text = new_text
        seg.status = "redrawn"
        return seg

    def lock_matches(self, lock: VoiceLock) -> bool:
        """True iff the on-disk reference still matches the manifest's lock.

        Guards ``redraw`` against an accidental reference re-record: if the
        user re-recorded mom.wav, the hash differs and we refuse the redraw
        (it would change the voice, not just the text).
        """
        return self.voice.ref_hash == lock.ref_hash and lock.verify_reference_unchanged()


__all__ = [
    "Segment",
    "VoiceLockModel",
    "NarrationManifest",
    "MANIFEST_FILENAME",
    "FULL_AUDIO_FILENAME",
]
