"""Tests for the CLI error surface (v0.3.0).

The CLI promises friendly errors + exit codes for the failure modes a user can
hit: a malformed/invalid ~/.qwenvoice/config.yml and render failures (missing
ffmpeg being the common case). Before the v0.3.0 fix both escaped as raw
tracebacks with exit code 1. The config path is injected via the module-level
DEFAULT_CONFIG_PATH so no test touches the real ~/.qwenvoice.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import qwenvoice.cli as cli

runner = CliRunner()


def _all_output(result) -> str:
    return result.output + (result.stderr or "")


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at a per-test config.yml."""
    p = tmp_path / "config.yml"
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", p)
    return p


class TestConfigErrorSurface:
    def test_malformed_yaml_exits_friendly(self, config_path: Path) -> None:
        config_path.write_text("talker_gguf: [unclosed\n  bad yaml: :::\n", encoding="utf-8")
        result = runner.invoke(
            cli.app,
            ["say", "--voice", "x.wav", "--ref-text", "r", "--text", "t"],
        )
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "config error" in out
        assert "yaml" in out

    def test_invalid_config_value_exits_friendly(self, config_path: Path) -> None:
        config_path.write_text("sample_rate: -1\n", encoding="utf-8")
        result = runner.invoke(
            cli.app,
            ["say", "--voice", "x.wav", "--ref-text", "r", "--text", "t"],
        )
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "config error" in out
        assert "sample_rate" in out

    def test_missing_config_still_works(self, config_path: Path, tmp_path: Path) -> None:
        # no config.yml on disk — defaults apply and the flow proceeds to the
        # voice-lock failure (exit 2), NOT a config error.
        result = runner.invoke(
            cli.app,
            ["say", "--voice", str(tmp_path / "nope.wav"), "--ref-text", "r", "--text", "t"],
        )
        assert result.exit_code == 2
        assert "config error" not in _all_output(result)
        assert "voice lock failed" in _all_output(result)

    def test_unreadable_config_exits_friendly(self, config_path: Path) -> None:
        # v0.4.0: a config path that cannot be read (here: a directory) used to
        # escape as a raw IsADirectoryError traceback, exit 1.
        config_path.mkdir()
        result = runner.invoke(
            cli.app,
            ["say", "--voice", "x.wav", "--ref-text", "r", "--text", "t"],
        )
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "config error" in out

    def test_non_utf8_config_exits_friendly(self, config_path: Path) -> None:
        config_path.write_bytes(b"talker_gguf: \xd5\xe2\xca\xc7\n")  # GB18030 bytes
        result = runner.invoke(
            cli.app,
            ["say", "--voice", "x.wav", "--ref-text", "r", "--text", "t"],
        )
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "config error" in out


class TestInputFileErrorSurface:
    """``book --file`` must not escape as a traceback (v0.4.0).

    A GBK/GB18030 novel and a path that is not a regular file are the two
    input shapes a Chinese long-text narration user actually hits.
    """

    def _book(self, tmp_path: Path, novel: Path, config_path: Path):
        (tmp_path / "mom.wav").write_bytes(b"RIFFfake" * 64)
        (tmp_path / "talker.gguf").write_bytes(b"fake-gguf")
        (tmp_path / "codec.gguf").write_bytes(b"fake-gguf")
        config_path.write_text(
            f"talker_gguf: {tmp_path / 'talker.gguf'}\n"
            f"codec_gguf: {tmp_path / 'codec.gguf'}\n",
            encoding="utf-8",
        )
        return runner.invoke(
            cli.app,
            [
                "book",
                "--voice", str(tmp_path / "mom.wav"),
                "--ref-text", "参考",
                "--file", str(novel),
                "--out", str(tmp_path / "book"),
            ],
        )

    def test_non_utf8_text_file_exits_friendly(
        self, tmp_path: Path, config_path: Path
    ) -> None:
        novel = tmp_path / "gbk_novel.txt"
        novel.write_bytes("这是第一句话。这是第二句话。".encode("gb18030"))
        result = self._book(tmp_path, novel, config_path)
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "cannot read input file" in out
        assert "UTF-8" in out

    def test_directory_as_text_file_exits_friendly(
        self, tmp_path: Path, config_path: Path
    ) -> None:
        directory = tmp_path / "novel_dir"
        directory.mkdir()
        result = self._book(tmp_path, directory, config_path)
        assert result.exit_code == 2
        out = _all_output(result)
        assert "Traceback" not in out
        assert "cannot read input file" in out


class TestRenderErrorSurface:
    def test_render_failure_exits_friendly_with_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_path: Path
    ) -> None:
        # artifacts must exist so the voice lock succeeds; synth is stubbed.
        (tmp_path / "mom.wav").write_bytes(b"RIFFfake" * 64)
        (tmp_path / "talker.gguf").write_bytes(b"fake-gguf")
        (tmp_path / "codec.gguf").write_bytes(b"fake-gguf")
        cfg = (
            f"talker_gguf: {tmp_path / 'talker.gguf'}\n"
            f"codec_gguf: {tmp_path / 'codec.gguf'}\n"
        )
        config_path.write_text(cfg, encoding="utf-8")

        def _boom(*args: object, **kwargs: object) -> object:
            raise FileNotFoundError("ffprobe")

        monkeypatch.setattr(cli, "synth_segment", lambda lock, text, config: object())
        monkeypatch.setattr(cli, "render_segment_with_text", _boom)
        result = runner.invoke(
            cli.app,
            [
                "say",
                "--voice", str(tmp_path / "mom.wav"),
                "--ref-text", "参考",
                "--text", "你好",
                "--out", str(tmp_path / "hello.mp3"),
            ],
        )
        assert result.exit_code == 4
        out = _all_output(result)
        assert "Traceback" not in out
        assert "render failed" in out
        assert "ffmpeg" in out
