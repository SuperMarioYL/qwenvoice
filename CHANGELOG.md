# Changelog

## [0.4.0] - 2026-11-12

### Fixed

- `redraw` no longer leaves the narration directory describing stale audio. Two
  defects: the updated `manifest.json` was written through the `output_dir`
  recorded at `book` time, so a relative `-o book` plus a `redraw` from another
  directory created a stray `manifest.json` there while the real one kept the
  old text and `synthesized` status; and `full.mp3` was never rebuilt, so the
  whole-book MP3 kept the pre-redraw take. The manifest is now written beside
  the file it was loaded from, and `redraw` re-concatenates `full.mp3` from the
  manifest's ordered segment files before writing the manifest
  (`qwenvoice/manifest.py`, `qwenvoice/cli.py`).
- `say --out <dir>/x.mp3` no longer deletes an existing `<dir>/seg_001.mp3`:
  `say` rendered straight into the output directory and renamed the file away,
  silently destroying a segment of a book living in the same directory. It now
  renders in a private temp dir and moves the result onto `--out`
  (`qwenvoice/cli.py`).
- `book` reports a friendly error instead of a traceback for an input file that
  cannot be read as UTF-8 (a GBK/GB18030 novel) or is not a regular file
  (`--file` pointing at a directory): exit 2 naming the file with a
  re-save-as-UTF-8 hint. The config guard gained the same `OSError` /
  `UnicodeDecodeError` coverage, so an unreadable or non-UTF-8
  `~/.qwenvoice/config.yml` exits 2 like a malformed one (`qwenvoice/cli.py`).

### Changed

- The documented `redraw` invocation now matches the CLI: both READMEs, the CLI
  module docstring and the site quickstart use `redraw --book ./book ...`, the
  form `--help` has always shown. The previous positional example exited with
  `Missing option '--book'` (`README.md`, `README.en.md`, `qwenvoice/cli.py`,
  `web/site.json`).

### Quality

- Version-lockstep test now also pins the newest `CHANGELOG.md` heading and
  `web/site.json` `meta.content_version`, the two surfaces the previous guard
  missed (`tests/test_version.py`).
- `examples/presentation_demo.py` imports are sorted, so `ruff check .` is clean
  from the repo root (CI only lints `qwenvoice tests`, which hid it).

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
