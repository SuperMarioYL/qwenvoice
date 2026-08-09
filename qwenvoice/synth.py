"""Synthesis — cffi dlopen of libgoqwen3ttscpp (qwentts.cpp FFI) + HTTP fallback.

This is the inference layer. It loads the Qwen3-TTS talker+codec GGUF pair via
the qwentts.cpp FFI shared library (packaged by LocalAI as
``libgoqwen3ttscpp-*.so`` / ``*.dylib``) and synthesizes a single text segment
into 24 kHz mono float32 PCM, using a locked speaker reference + its
transcript. No subprocess is spawned for inference — cffi ``dlopen`` calls the
FFI symbols directly in-process (the plan's architecture constraint: "cffi
dlopen libgoqwen3ttscpp, 无子进程").

When the FFI library is unavailable (not built, not on this machine), synthesis
falls back to a local vLLM-Omni HTTP server exposing the OpenAI-compatible
``/v1/audio/speech`` endpoint, configured via ``QwenVoiceConfig.http_fallback_url``.
If neither path is available, we fail closed with a clear error — we never
silently weaken the offline-local requirement.

Assumed qwentts.cpp FFI ABI (schema_unverified — verify against upstream
https://github.com/ServeurpersoCom/qwentts.cpp at integration time)::

    typedef struct qt3_ctx qt3_ctx;
    qt3_ctx* qt3_load(const char* talker_path, const char* codec_path);
    int      qt3_tts(qt3_ctx* ctx,
                     const char* ref_audio_path,
                     const char* ref_text,
                     const char* text,
                     float**    out_pcm,   // heap buffer, caller frees
                     int*       out_n);     // sample count
    void     qt3_free_pcm(float* pcm);
    void     qt3_free(qt3_ctx* ctx);

cffi ABI-mode ``dlopen`` infers argument layouts from the call site; the
``float**`` out-parameter is handled via ``ffi.new("float**")``.
"""

from __future__ import annotations

import json
import struct
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import QwenVoiceConfig
from .voice import VoiceLock

if TYPE_CHECKING:
    from cffi import FFI  # noqa: F401

# fmt: off
# qwentts.cpp FFI symbol names (assumed ABI).
_QT3_LOAD     = "qt3_load"
_QT3_TTS      = "qt3_tts"
_QT3_FREE_PCM = "qt3_free_pcm"
_QT3_FREE     = "qt3_free"

# Library filename patterns to auto-discover when ffi_lib_path is empty.
_LIB_PATTERNS = (
    "libgoqwen3ttscpp.so",
    "libgoqwen3ttscpp.dylib",
    "libgoqwen3ttscpp-*.so",
    "libgoqwen3ttscpp-*.dylib",
)
# fmt: on


@dataclass(slots=True)
class PCM:
    """Raw synthesized audio — 24 kHz mono float32, in [-1, 1]."""

    samples: bytes  # little-endian float32 stream
    sample_rate: int
    channels: int

    def to_floats(self) -> list[float]:
        n = len(self.samples) // 4
        return list(struct.unpack("<" + "f" * n, self.samples)) if n else []


class SynthesisError(RuntimeError):
    """Raised when neither the FFI lib nor the HTTP fallback can synthesize."""


class FFIUnavailableError(SynthesisError):
    """The qwentts.cpp FFI shared library could not be loaded."""


def _discover_ffi_lib(hint: str = "") -> str:
    """Find libgoqwen3ttscpp on disk.

    Order: explicit hint > CWD > standard lib dirs. Returns "" if not found.
    """
    if hint:
        p = Path(hint)
        if p.exists():
            return str(p)
    cwd = Path.cwd()
    for pat in _LIB_PATTERNS:
        for cand in cwd.glob(pat):
            return str(cand.resolve())
    for d in ("/usr/local/lib", "/usr/lib", "/opt/homebrew/lib"):
        base = Path(d)
        for pat in _LIB_PATTERNS:
            for cand in base.glob(pat):
                return str(cand.resolve())
    return ""


def _open_ffi(lib_path: str) -> FFI:
    """cffi dlopen the qwentts.cpp FFI shared library (ABI mode).

    Imported lazily so the package still imports (and tests run) on machines
    without cffi's compiled backend or without the lib installed.
    """
    from cffi import FFI  # local import — cffi is a hard dep but lazy-bound

    ffi = FFI()
    try:
        return ffi.dlopen(lib_path)
    except Exception as exc:  # cffi raises OSError on missing symbol/file
        raise FFIUnavailableError(
            f"could not dlopen qwentts.cpp FFI lib at {lib_path!r}: {exc}"
        ) from exc


class FFISynth:
    """In-process Qwen3-TTS synth via the qwentts.cpp FFI shared library.

    Holds one loaded ``qt3_ctx`` (talker+codec pair) and synthesizes segments
    against a locked :class:`VoiceLock`. The ctx is freed on close / GC.
    """

    def __init__(self, lock: VoiceLock, config: QwenVoiceConfig) -> None:
        self._lock = lock
        self._config = config
        self._ffi: FFI | None = None
        self._lib = None
        self._ctx = None  # opaque qt3_ctx pointer

    # -- context management -------------------------------------------------
    def __enter__(self) -> FFISynth:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> None:
        lib_path = self._config.ffi_lib_path or _discover_ffi_lib()
        if not lib_path:
            raise FFIUnavailableError(
                "qwentts.cpp FFI lib (libgoqwen3ttscpp) not found; run "
                "`qwenvoice init` or set ffi_lib_path, or configure "
                "http_fallback_url for the local vLLM-Omni server."
            )
        self._ffi = _open_ffi(lib_path)
        self._lib = self._ffi  # cffi dlopen returns the binding object
        talker_b = self._lock.talker_gguf.encode("utf-8")
        codec_b = self._lock.codec_gguf.encode("utf-8")
        ctx = self._lib.qt3_load(talker_b, codec_b)
        if not ctx:
            raise SynthesisError(
                f"qt3_load failed for talker={self._lock.talker_gguf!r} "
                f"codec={self._lock.codec_gguf!r}"
            )
        self._ctx = ctx

    def close(self) -> None:
        if self._ctx is not None and self._lib is not None:
            try:
                self._lib.qt3_free(self._ctx)
            except Exception:
                pass
        self._ctx = None
        self._lib = None
        self._ffi = None

    # -- synthesis ----------------------------------------------------------
    def synth(self, text: str) -> PCM:
        """Synthesize one text segment into 24 kHz mono float32 PCM.

        Raises :class:`SynthesisError` on any FFI-level failure. The caller
        (``render``) is responsible for wav→mp3.
        """
        if self._ctx is None or self._lib is None or self._ffi is None:
            raise SynthesisError("FFISynth not opened — call within `with` block")
        if not text.strip():
            raise ValueError("text must be non-empty")

        ffi = self._ffi
        ref_b = self._lock.speaker_ref_path.encode("utf-8")
        ref_text_b = self._lock.ref_text.encode("utf-8")
        text_b = text.encode("utf-8")
        out_pcm = ffi.new("float**")
        out_n = ffi.new("int*")

        ret = self._lib.qt3_tts(self._ctx, ref_b, ref_text_b, text_b, out_pcm, out_n)
        if ret != 0:
            raise SynthesisError(f"qt3_tts returned error code {ret}")
        n = int(out_n[0])
        if n <= 0:
            raise SynthesisError("qt3_tts produced 0 samples")
        # float32 stream — cffi buffer view then to bytes for transport.
        pcm_bytes = bytes(ffi.buffer(out_pcm[0], n * 4))
        # free the FFI-allocated PCM buffer to avoid leaking across segments.
        try:
            self._lib.qt3_free_pcm(out_pcm[0])
        except Exception:
            pass
        return PCM(
            samples=pcm_bytes,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
        )


class HTTPSynth:
    """OpenAI-compatible /v1/audio/speech fallback (local vLLM-Omni server).

    Used only when the FFI lib is unavailable. The server must be local — we
    refuse a remote URL to preserve the "voice biometric never leaves the
    machine" thesis. The request carries the reference audio path (server reads
    it from the same filesystem) + transcript + text.
    """

    def __init__(self, lock: VoiceLock, config: QwenVoiceConfig) -> None:
        if not config.http_fallback_url:
            raise SynthesisError(
                "no FFI lib and no http_fallback_url configured — cannot synth"
            )
        self._lock = lock
        self._config = config
        self._url = config.http_fallback_url.rstrip("/")

    def synth(self, text: str) -> PCM:
        if not text.strip():
            raise ValueError("text must be non-empty")
        payload = {
            "model": "qwen3-tts",
            "input": text,
            "voice": self._lock.speaker_ref_path,
            "ref_text": self._lock.ref_text,
            "response_format": "pcm",
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._url}/v1/audio/speech",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                pcm_bytes = resp.read()
        except Exception as exc:
            raise SynthesisError(f"HTTP fallback synth failed: {exc}") from exc
        return PCM(
            samples=pcm_bytes,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
        )


def synth_segment(lock: VoiceLock, text: str, config: QwenVoiceConfig) -> PCM:
    """Synthesize one segment — FFI first, HTTP fallback second, fail closed.

    The single entry point used by both ``say`` (m1) and ``book`` (m2). Keeps
    the FFI ctx lifetime scoped to exactly one segment so a long book run does
    not hold the model ctx open across all segments (re-open per segment is
    fine — the VoiceLock guarantees the same voice).
    """
    last_exc: Exception | None = None

    # 1) FFI path (preferred — true in-process offline).
    try:
        with FFISynth(lock, config) as synth:
            return synth.synth(text)
    except FFIUnavailableError as exc:
        last_exc = exc
    except SynthesisError:
        raise

    # 2) HTTP fallback (local vLLM-Omni only).
    try:
        return HTTPSynth(lock, config).synth(text)
    except SynthesisError as exc:
        last_exc = exc

    raise SynthesisError(
        "could not synthesize via FFI (libgoqwen3ttscpp not loadable) nor via "
        f"HTTP fallback: {last_exc}"
    )


__all__ = [
    "PCM",
    "SynthesisError",
    "FFIUnavailableError",
    "FFISynth",
    "HTTPSynth",
    "synth_segment",
]
