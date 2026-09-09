# Changelog

## [0.2.0] - 2026-09-10

### Fixed

- Chinese consecutive terminators (`？！`, `！！`, `。。。`) are no longer silently
  dropped or turned into spurious garbage segments. `split_sentences` keeps a
  terminator run attached to its sentence and derives the trailing fragment from
  the last match boundary, so every input character survives segmentation intact
  (`qwenvoice/segment.py`).
- The HTTP fallback now enforces its documented local-only contract:
  `http_fallback_url` must point at `localhost` or a loopback/private/link-local
  address (covers Docker-bridge and LAN vLLM servers); public endpoints and
  remote hostnames are refused with a clear error, so the reference transcript
  and audio path can never leave the machine (`qwenvoice/synth.py`).
- CI on `main` is green again. The render round-trip test crashed with
  `FileNotFoundError: 'ffprobe'` on runners without ffmpeg because pydub's
  `AudioSegment.from_file` probes media even for in-memory wav; the test now
  skips cleanly without ffprobe, and CI installs ffmpeg so the render path is
  exercised for real (`tests/test_render.py`, `.github/workflows/ci.yml`).

### Added

- This `CHANGELOG.md`.
- Version-lockstep test: `pyproject.toml`, the `VERSION` file,
  `qwenvoice.__version__` and the CLI `--version` output must always agree
  (`tests/test_version.py`).

## [0.1.0] - 2026-08-09

Initial release — m1 single-segment speech pipeline.

- `qwenvoice init` — artifact discovery (talker/codec GGUF, qwentts.cpp FFI lib,
  ffmpeg) writing `~/.qwenvoice/config.yml`.
- `qwenvoice say` — lock a speaker reference + transcript, synthesize one
  segment via the qwentts.cpp FFI (`qt3_load`/`qt3_tts`) or a local
  OpenAI-compatible `/v1/audio/speech` endpoint, render to MP3.
- Chinese sentence-boundary segmentation primitives (`split_sentences`,
  `segment_single`, `segment_long_text`) and the `NarrationManifest` /
  `VoiceLock` data model.
- `book` / `redraw` ship as documented placeholders (exit 64).
