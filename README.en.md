[简体中文](./README.md) · [Website](https://qwenvoice.lei6393.com) · [GitHub](https://github.com/SuperMarioYL/qwenvoice)

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/hero-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/hero-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/hero-dark.svg">
  <img src="./assets/presentation/hero-light.svg" width="960" alt="Hero diagram">
</picture>

# QwenVoice

**Prepare Chinese narration one segment at a time**

QwenVoice combines a reference-audio record, Chinese sentence segmentation and a single-segment speech command. Its say path uses configured Qwen3-TTS artifacts; long-book and redraw commands are not yet implemented.

## Why use it

A narration workflow needs to know which text segment, reference recording and model files produced an output. QwenVoice keeps these inputs explicit, while its local segmenter lets you inspect Chinese sentence boundaries before attempting synthesis.

- **Inspect segment boundaries** — The segmenter accumulates whole sentences under a soft character limit.
- **Record reference identity** — VoiceLock hashes reference bytes plus transcript and records model paths.
- **Separate audio stages** — Synthesis returns PCM; rendering converts audio and writes the output file.

## Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/architecture-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/architecture-dark.svg">
  <img src="./assets/presentation/architecture-light.svg" width="960" alt="Architecture diagram">
</picture>

segment.py provides single- and long-text segmentation helpers. VoiceLock validates reference/model paths and fingerprints the reference content. synth_segment tries the qt3_* FFI interface, then a configured HTTP speech endpoint when the FFI is unavailable. render.py handles the returned PCM and MP3 output.

| Component | Responsibility |
| --- | --- |
| `Chinese text` | sentence-boundary segments |
| `VoiceLock` | reference and artifact paths |
| `Synth adapter` | FFI or HTTP speech |
| `Audio renderer` | PCM to MP3 |

## Install and quickstart

Python 3.12+ and uv for the text demo. Audio synthesis additionally needs compatible talker/codec GGUF files, an FFI library or configured endpoint, a usable reference sample, and FFmpeg for MP3 rendering.

```bash
git clone https://github.com/SuperMarioYL/qwenvoice.git
cd qwenvoice
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

The complete offline example runs segment_long_text on supplied Chinese text and checks that concatenating these segments reconstructs the input. It generates no audio.

```bash
.venv/bin/python examples/presentation_demo.py
```

## Recorded demo

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/process-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/process-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/process-dark.svg">
  <img src="./assets/presentation/process-light.svg" width="960" alt="Process diagram">
</picture>

The local segmenter returns three ordered segments and preserves this example’s text.

```text
{
  "input": "缓存保存可复用的结果。数据变化后需要失效。接下来，为每类数据选择有效期。",
  "soft_limit": 18,
  "segments": [
    {
      "id": 1,
      "text": "缓存保存可复用的结果。"
    },
    {
      "id": 2,
      "text": "数据变化后需要失效。"
    },
    {
      "id": 3,
      "text": "接下来，为每类数据选择有效期。"
    }
  ]
}
Input preserved: True
Scope: sentence-boundary text segmentation only; no voice cloning or audio synthesis.
```

The complete command and output are recorded in [docs/demo-results.json](./docs/demo-results.json). Inputs and reproduction code are included in the repository.

## Usage

Replace artifact and recording paths with real compatible files before running the audio commands. init reports availability and writes ~/.qwenvoice/config.yml; it can write configuration even when artifacts are missing. say locks inputs and synthesizes one segment. Use a voice sample you are authorized to synthesize from.

```bash
.venv/bin/qwenvoice init --talker ./models/talker.gguf --codec ./models/codec.gguf --ffi-lib ./libgoqwen3ttscpp.dylib
.venv/bin/qwenvoice say --voice ./reference.wav --ref-text "参考录音的准确转录" --text "你好，欢迎收听。" --out ./hello.mp3
```

## Configuration

The YAML config holds talker_gguf, codec_gguf, ffi_lib_path, http_fallback_url, sample_rate, channels, seed and max_chars_per_segment. Configure the HTTP base with init --http-fallback http://127.0.0.1:8000; say has no --http-fallback option. The implementation appends /v1/audio/speech. It does not enforce loopback URLs, so keeping the endpoint local is an operator configuration choice.

## Integrations and responsibilities

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="./assets/presentation/integrations-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="./assets/presentation/integrations-dark.svg">
  <img src="./assets/presentation/integrations-light.svg" width="960" alt="Integrations diagram">
</picture>

The Python package does not include model weights or the FFI library. Its reference hash identifies input changes, not a guarantee of speaker similarity or deterministic audio. A speech endpoint must understand the request’s reference-path and transcript fields.

| Route | Implemented role |
| --- | --- |
| Chinese text | local sentence splitter |
| Reference audio | recording plus transcript |
| GGUF artifacts | talker and codec paths |
| FFI / HTTP | configured synthesis adapters |
| FFmpeg / pydub | audio rendering helpers |

## Limits and next steps

- book and redraw are placeholders that return exit 64. No complete long-book narration or selective redraw workflow is implemented.
- The soft limit may be exceeded by a single long sentence. The segmenter is punctuation-based; it does not use jieba word boundaries in its current implementation.
- This demo validates text segmentation only. Native ABI compatibility, voice quality and audio output were not tested.

Implemented: artifact discovery, reference fingerprinting, single-segment synthesis adapters and text/audio helper modules. Next: compatible-runtime verification, long-book orchestration and redraw with measured audio consistency. No voice-quality or byte-identical redraw promise is established by the current demo.

## License and contributions

See [LICENSE](./LICENSE). When reporting an issue, include a minimal input, the command, and the observed output.
