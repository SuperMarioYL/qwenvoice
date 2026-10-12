# Changelog

## [0.3.0] - 2026-10-13

### Fixed

- GitHub releases now carry their artifacts. The release workflow built the
  wheel, sdist and checksums but only stored them as a workflow artifact —
  nothing was attached to the release, so v0.2.0 shipped with zero assets. The
  workflow now uploads `dist/*` to the release on every tag push
  (`.github/workflows/release.yml`).
- A malformed or invalid `~/.qwenvoice/config.yml` no longer escapes as a raw
  yaml/pydantic traceback: `say`/`book`/`redraw` exit 2 with a message naming
  the config path and a fix hint. Render failures (most commonly a missing
  ffmpeg/ffprobe) exit 4 with an install hint instead of a raw traceback
  (`qwenvoice/cli.py`).
- The READMEs no longer claim the HTTP fallback "does not enforce loopback
  URLs" — that was false since v0.2.0, when `HTTPSynth` started refusing
  public/remote endpoints. Both READMEs now state the enforced contract
  (`README.md`, `README.en.md`).

### Added

- The plan's m2/m3 happy path is wired: `qwenvoice book` segments a long
  Chinese text, synthesizes every segment with the locked voice, writes
  `seg_NNN.mp3` + concatenated `full.mp3` + `manifest.json`; `qwenvoice
  redraw` re-synthesizes a single manifest segment with edited text, refuses a
  re-recorded reference (lock-hash drift) and never rewrites any other
  segment's file. The orchestration is covered by mock-synth tests; audio
  output still requires a compatible Qwen3-TTS runtime (`qwenvoice/cli.py`,
  `tests/test_narration.py`).

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
