#!/usr/bin/env bash
# fetch_model.sh — download the Qwen3-TTS talker + codec GGUF pair.
#
# The talker (qwen-talker-1.7b-base-Q8_0.gguf) and the 12 Hz codec/tokenizer
# (qwen-tokenizer-12hz-Q8_0.gguf) are the two weights qwentts.cpp loads. Both
# are fetched to the local models/ dir — nothing is uploaded; the reference
# audio stays on your machine.
#
# Usage:
#   scripts/fetch_model.sh [--dest models]
set -euo pipefail

DEST="${1:-models}"
mkdir -p "$DEST"

TALKER="qwen-talker-1.7b-base-Q8_0.gguf"
CODEC="qwen-tokenizer-12hz-Q8_0.gguf"

# GGUF mirror — adjust to a reachable Hugging Face / ModelScope mirror if the
# default is blocked. Both files are public Qwen3-TTS GGUF quants.
HF_BASE="${HF_BASE:-https://huggingface.co}"

fetch() {
    local url="$1"; local out="$2"
    if [[ -f "$out" ]]; then
        echo "exists: $out"
        return
    fi
    echo "downloading: $url -> $out"
    if command -v curl >/dev/null 2>&1; then
        curl -L --fail -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$out" "$url"
    else
        echo "error: need curl or wget to download" >&2
        exit 1
    fi
}

# NOTE: replace the exact repo/path with the live Qwen3-TTS GGUF release once
# the canonical HF repo is published. These URLs are the conventional layout.
fetch "${HF_BASE}/Qwen/Qwen3-TTS-12hz-1.7B-Base-GGUF/resolve/main/qwen-talker-1.7b-base-Q8_0.gguf" \
      "${DEST}/${TALKER}"
fetch "${HF_BASE}/Qwen/Qwen3-TTS-12hz-1.7B-Base-GGUF/resolve/main/qwen-tokenizer-12hz-Q8_0.gguf" \
      "${DEST}/${CODEC}"

echo
echo "fetched to ${DEST}/:"
ls -lh "${DEST}/${TALKER}" "${DEST}/${CODEC}"
echo
echo "next: qwenvoice init --talker ${DEST}/${TALKER} --codec ${DEST}/${CODEC}"
