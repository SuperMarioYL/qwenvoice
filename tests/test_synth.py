"""Tests for qwenvoice.synth — HTTP fallback endpoint locality guard (v0.2.0).

The plan's thesis ("voice biometric never leaves the machine", out_of_scope:
cloud upload — NEVER) requires the /v1/audio/speech fallback to be local. The
constructor validates the host without making any network call, so these tests
run fully offline.
"""

from __future__ import annotations

import pytest

from qwenvoice.config import QwenVoiceConfig
from qwenvoice.synth import HTTPSynth, SynthesisError
from qwenvoice.voice import VoiceLock


def _lock() -> VoiceLock:
    return VoiceLock(
        speaker_ref_path="mom.wav",
        ref_text="今天天气真好",
        talker_gguf="t.gguf",
        codec_gguf="c.gguf",
        ffi_lib_path="",
        ref_hash="sha256:x",
        seed=42,
    )


class TestHTTPLocalEndpointGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://[::1]:8000",
            "http://192.168.1.10:8000",  # LAN server
            "http://10.0.0.5:8000",  # Docker/LAN
            "http://172.17.0.2:8000",  # Docker bridge
            "https://127.0.0.1:8443",
        ],
    )
    def test_local_endpoints_accepted(self, url: str) -> None:
        HTTPSynth(_lock(), QwenVoiceConfig(http_fallback_url=url))

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.example-tts.cloud",  # remote hostname
            "http://8.8.8.8:8000",  # public IP (is_global, not is_private)
            "http://1.2.3.4:8000",  # public IP
            "http://mybox.example.com:8000",  # non-localhost hostname
            "127.0.0.1:8000",  # no scheme — no host parsed
            # note: TEST-NET doc ranges (203.0.113.0/24 etc.) are classified
            # is_private=True by modern ipaddress and therefore allowed — they
            # are unroutable, so nothing can actually leave the machine.
        ],
    )
    def test_remote_endpoints_refused(self, url: str) -> None:
        with pytest.raises(SynthesisError):
            HTTPSynth(_lock(), QwenVoiceConfig(http_fallback_url=url))

    def test_refusal_message_names_the_constraint(self) -> None:
        with pytest.raises(SynthesisError, match="local"):
            HTTPSynth(_lock(), QwenVoiceConfig(http_fallback_url="https://api.example-tts.cloud"))

    def test_no_fallback_configured(self) -> None:
        with pytest.raises(SynthesisError, match="no FFI lib"):
            HTTPSynth(_lock(), QwenVoiceConfig())
