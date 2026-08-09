<div align="right"><sub><a href="./README.en.md">English</a>&nbsp;&nbsp;⇄&nbsp;&nbsp;<b>简体中文</b></sub></div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/hero-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/hero-light.svg">
    <img src="./assets/hero-light.svg" width="880" alt="QwenVoice — 本地离线中文音色克隆">
  </picture>
</p>

<p align="center"><sub>QwenVoice 是用你自己的克隆音色、本地离线朗读中文长文的命令行工具——音色生物特征从不上云。</sub></p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="license"></a>
  <a href="https://github.com/SuperMarioYL/qwenvoice/releases"><img src="https://img.shields.io/github/v/release/SuperMarioYL/qwenvoice" alt="latest release"></a>
  <a href="https://github.com/SuperMarioYL/qwenvoice/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/SuperMarioYL/qwenvoice/ci.yml?label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue" alt="python">
  <img src="https://img.shields.io/badge/runs-offline-success" alt="offline">
</p>

**用一段 5 秒的家人参考音频，本地把整篇中文长文朗读成分段有声 MP3，逐段重绘而不改变音色。**

<h2><img src="https://api.iconify.design/tabler:topology-star-3.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 架构</h2>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./assets/atlas-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="./assets/atlas-light.svg">
    <img src="./assets/atlas-light.svg" width="880" alt="架构：文本+参考音频 → 断句+VoiceLock → cffi FFI qt3_tts → 分段 MP3 + manifest">
  </picture>
</p>

Qwen3-TTS 的本地 GGUF 推理由第三方 [qwentts.cpp](https://github.com/ServeurpersoCom/qwentts.cpp)（LocalAI 打包为 FFI 共享库 `libgoqwen3ttscpp`）跑通——这是首个能在消费级硬件本地离线、支持中文音色克隆的实用路径。QwenVoice 把它包成一条命令：锁参考音频 + 其转写 + talker/codec 双 GGUF，经 cffi FFI 在进程内合成（`qt3_load` + `qt3_tts`，无推理子进程），ffmpeg 把 PCM 转成分段 MP3。`VoiceLock` + 每段固定种子让逐段重绘不变音色——这是云端 TTS 与 GPT-SoVITS 都没有的契约。

## 为什么做这个

云端中文 TTS（Azure、字节火山引擎）质量好，但要求把音色样本上传服务器——音色是生物特征，中国用户普遍拒绝；长文按调用计费，每段重绘还会改音色，同篇文本音色漂移。ElevenLabs 中文弱、无离线、数据出境有合规风险。Qwen3-TTS 在 2026 年 8 月进入 llama.cpp / qwentts.cpp 路线后，"本地离线中文克隆"第一次从"需要 GPU + Python"降到"消费级硬件 + 一条命令"。QwenVoice 把这个 primitive 接上"音色不上云 + 中文长文逐段重绘"这一层——国产模型本地推理，参考音频始终不出机器。

### 与现有方案对比

| 维度 | QwenVoice | GPT-SoVITS (~40k star) | 云端 TTS (Azure / 火山) |
|---|---|---|---|
| 本地离线推理 | ✓ cffi FFI（qwentts.cpp） | ✓ Python + GPU | ✗ 需联网 |
| 音色样本上云 | ✗ 永不上云 | ✗ 本地 | ✓ 需上传 |
| 消费级硬件可跑 | ✓ GGUF Q8 | ✗ 需 GPU | ✓（云端） |
| 逐段重绘不变音色 | ✓ VoiceLock + 固定 seed | partial（无 in-place 契约） | ✗ 重绘改音色 |
| 中文长文分段 | ✓ jieba 断句 | partial | partial |
| 模型成熟度 / 音色自然度 | partial（Qwen3-TTS 早期） | ✓ 更成熟 | ✓ 最好 |

GPT-SoVITS 在模型成熟度与音色自然度上仍领先；QwenVoice 的差异在"消费级硬件 + 逐段重绘不变音色"这一层，不在合成质量。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [用法](#用法)
- [Demo](#demo)
- [配置](#配置)
- [付费与商业层](#付费与商业层)
- [路线图](#路线图)
- [License](#license)

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 安装</h2>

```bash
# 需要 Python 3.12 + ffmpeg
uv tool install qwenvoice          # 或：pipx install qwenvoice
```

首次运行需下载 Qwen3-TTS talker + codec 两份 GGUF（约 1.7B 量化权重）并定位 qwentts.cpp FFI 共享库：

```bash
scripts/fetch_model.sh             # 下载 talker + codec GGUF 到 models/
qwenvoice init                     # 探测 GGUF / libgoqwen3ttscpp / ffmpeg，写 ~/.qwenvoice/config.yml
```

<h2><img src="https://api.iconify.design/tabler:rocket.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 快速开始</h2>

三条命令从冷启动到第一段克隆音色 MP3（合成耗时除外，每步 < 60 秒）：

```bash
qwenvoice init                                                      # 1. 定位模型与 FFI 库
# 录一段 5–15 秒家人说话的 mom.wav，记下其文字转写
qwenvoice say --voice mom.wav --ref-text "今天天气真好" \
  --text "你好，欢迎使用 QwenVoice。" -o hello.mp3                  # 2. 用家人音色读一句话
open hello.mp3                                                      # 3. 听到家人音色读出这句话
```

<details>
<summary>示例输出</summary>

```
$ qwenvoice init
artifact           status   path
talker GGUF        ok       models/qwen-talker-1.7b-base-Q8_0.gguf
codec/tokenizer    ok       models/qwen-tokenizer-12hz-Q8_0.gguf
qwentts.cpp FFI    ok       ./libgoqwen3ttscpp.dylib
ffmpeg             ok       ffmpeg
wrote /Users/you/.qwenvoice/config.yml

$ qwenvoice say --voice mom.wav --ref-text "今天天气真好" --text "你好，欢迎使用 QwenVoice。" -o hello.mp3
locking voice...
voice lock: sha256:7c4a8d09ca...
synthesizing 1 segment (16 chars)...
synthesizing via qwentts.cpp FFI…
rendering MP3 → hello.mp3...
done → hello.mp3
ref_hash=sha256:7c4a8d09ca... seed=42
```
</details>

<h2><img src="https://api.iconify.design/tabler:terminal-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 用法</h2>

`qwenvoice` 当前实现 m1（`say` 单段合成）。`book`（m2 长文分段）与 `redraw`（m3 逐段重绘）为占位，见[路线图](#路线图)。

```bash
# 单段合成（m1，已实现）：锁音色 → FFI 合成 → MP3
qwenvoice say \
  --voice mom.wav \
  --ref-text "今天天气真好" \
  --text "你好，欢迎使用 QwenVoice。" \
  -o hello.mp3

# 指定不同的固定种子（同 lock + 同 seed → 同音色，用于逐段重绘契约）
qwenvoice say --voice mom.wav --ref-text "今天天气真好" --text "第二句话。" --seed 7 -o seg2.mp3

# 覆盖 talker/codec GGUF 或 FFI 库路径（不走 config）
qwenvoice say --voice mom.wav --ref-text "..." --text "..." \
  --talker models/qwen-talker-1.7b-base-Q8_0.gguf \
  --codec  models/qwen-tokenizer-12hz-Q8_0.gguf \
  --ffi-lib ./libgoqwen3ttscpp.dylib -o out.mp3

# 无 FFI 库时回退到本地 vLLM-Omni HTTP server（OpenAI 兼容 /v1/audio/speech）
qwenvoice say --voice mom.wav --ref-text "..." --text "..." \
  --http-fallback http://127.0.0.1:8000 -o out.mp3
```

参考音频需 ≥ 5 秒且必须提供其文字转写（`--ref-text`）——Qwen3-TTS Base 克隆同时需要参考音频 + 转写。若 ≥5 秒参考仍克隆不出可辨识音色，触发 [kill criteria](#路线图) m1 gate，halt。

<h2><img src="https://api.iconify.design/tabler:photo.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> Demo</h2>

![demo](assets/demo.gif)

10 分钟 happy path：`qwenvoice init` → 录 `mom.wav` → `qwenvoice say ... -o hello.mp3` → 播放。终端录制见 [`assets/demo.cast`](./assets/demo.cast)，vhs 脚本见 [`docs/demo.tape`](./docs/demo.tape)（首次打 tag 时由 `.github/workflows/demo.yml` 渲染成 `assets/demo.gif`）。

<h2><img src="https://api.iconify.design/tabler:adjustments.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 配置</h2>

`~/.qwenvoice/config.yml`（由 `qwenvoice init` 写入，可被命令行 flag 覆盖）：

| key | 类型 | 默认 | 含义 |
|---|---|---|---|
| `talker_gguf` | str | `qwen-talker-1.7b-base-Q8_0.gguf` | Qwen3-TTS talker GGUF 路径 |
| `codec_gguf` | str | `qwen-tokenizer-12hz-Q8_0.gguf` | 12 Hz codec/tokenizer GGUF（talker 同级 `*tokenizer*.gguf` 自动发现） |
| `ffi_lib_path` | str | `""` | `libgoqwen3ttscpp-*.so/.dylib` 路径，空则自动探测 |
| `http_fallback_url` | str | `""` | 本地 vLLM-Omni `OpenAI 兼容 /v1/audio/speech` 回退地址 |
| `ffmpeg_bin` | str | `ffmpeg` | ffmpeg 二进制路径（wav→mp3 + 拼接） |
| `sample_rate` | int | `24000` | PCM 采样率（Qwen3-TTS = 24 kHz） |
| `channels` | int | `1` | 声道数（mono） |
| `seed` | int | `42` | 每段固定种子（重绘不变音色） |
| `max_chars_per_segment` | int | `200` | jieba 断句每段软上限（不跨句切断） |

<h2><img src="https://api.iconify.design/tabler:cash.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 付费与商业层</h2>

付费层是面向不会装 Python / cffi FFI 库的普通用户的**一键桌面安装器 + 家人音色包管理 GUI**（本地运行，非云端推理；音色始终在本地处理）：

| 层 | 形态 | 价格 | 说明 |
|---|---|---|---|
| CLI + 推理引擎 | 开源 CLI（本仓库） | 免费 OSS（MIT） | `say` / `book` / `redraw` 全功能，永久免费 |
| 桌面安装器 | 一次性买断 GUI | ¥39–69 / seat | 一键安装 + 音色包管理 + 可视化分段重绘，面向非技术用户 |
| 直连定制 | 微信直连 design-partner | 按需 | 整本书克隆朗读换一份 `NarrationManifest` 样本 + 反馈 |

支付走爱发电（一次性赞助 + license key）+ 微信支付/支付宝直收款；安装器 .dmg/.exe 托管在 GitHub Releases（免费）。**不按字符计费、不托管音色**——那会重新引入我们正在逃离的云端模型。v0.1 仅以 CLI 暗示该层、不构建；GUI 在 Day-30 用户验证通过（≥3/5 目标用户说每周用）后才动工。

<h2><img src="https://api.iconify.design/tabler:map-2.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> 路线图</h2>

- [x] **m1 锁音色 + 单段合成** — `qwenvoice say` 离线跑通：锁参考音频 + 转写 + talker/codec GGUF，经 qwentts.cpp FFI 产出单段克隆音色 MP3。
- [ ] **m2 长文分段 + 有声书** — `qwenvoice book`：jieba 分段、逐段离线合成、写 `seg_001..NNN.mp3` + 拼接 `full.mp3` + `manifest.json`。
- [ ] **m3 逐段重绘** — `qwenvoice redraw`：只重画指定段，验证其余段字节不变、音色锁定（moat demo）。
- [ ] 桌面安装器 GUI（付费层，待 Day-30 验证）。

**Kill criteria**（falsifiable，非空话）：① FFI 路径 broken/abandoned >2 周且 HTTP 回退亦不可用 → halt；② m1 gate：≥5s 参考仍克隆不出可辨识音色 → 核心论点为假，halt；③ 4 周末 + 3 项 launch 活动后安装 <50 且 <3/5 目标用户说每周用 → kill；④ GPT-SoVITS 先发消费级 GGUF 一键 GUI → 2 季度内 kill 或 pivot。

<h2><img src="https://api.iconify.design/tabler:license.svg?color=%230071E3&width=24" height="22" align="absmiddle" alt=""> License</h2>

[MIT](./LICENSE) © 2026 SuperMarioYL。Issue 与 PR 欢迎：[github.com/SuperMarioYL/qwenvoice/issues](https://github.com/SuperMarioYL/qwenvoice/issues)。

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
