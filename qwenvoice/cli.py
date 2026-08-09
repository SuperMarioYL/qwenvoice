"""QwenVoice CLI — typer surface for ``say`` / ``book`` / ``redraw`` / ``init``.

m1 implements ``say`` (single-segment synth) and ``init`` (artifact discovery).
``book`` (m2) and ``redraw`` (m3) are stubbed with TODO markers — the manifest
and segment primitives they depend on are already in place, so m2/m3 are a
matter of wiring, not new design.

Examples (m1 happy path)::

    qwenvoice init
    qwenvoice say --voice mom.wav --ref-text "今天天气真好" --text "你好，欢迎使用 QwenVoice。" -o hello.mp3
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import DEFAULT_CONFIG_PATH, QwenVoiceConfig, discover_codec_gguf
from .render import render_segment_with_text
from .segment import segment_single
from .synth import SynthesisError, synth_segment
from .voice import VoiceLock

app = typer.Typer(
    name="qwenvoice",
    help="本地离线中文音色克隆 + 长文分段有声 MP3（Qwen3-TTS / qwentts.cpp FFI）。",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"qwenvoice {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show qwenvoice version and exit.",
    ),
) -> None:
    """QwenVoice — local offline Chinese voice cloning via Qwen3-TTS."""


# ---------------------------------------------------------------------------
# init — artifact discovery / config bootstrap (m1)
# ---------------------------------------------------------------------------
@app.command()
def init(
    talker: Path = typer.Option(
        Path("qwen-talker-1.7b-base-Q8_0.gguf"),
        "--talker",
        help="Path to the Qwen3-TTS talker GGUF.",
    ),
    codec: Path = typer.Option(
        None,
        "--codec",
        help="Path to the 12 Hz codec/tokenizer GGUF (auto-discovered if omitted).",
    ),
    ffi_lib: Path = typer.Option(
        None,
        "--ffi-lib",
        help="Path to libgoqwen3ttscpp-*.so/.dylib (auto-detected if omitted).",
    ),
    http_fallback: str = typer.Option(
        "",
        "--http-fallback",
        help="Local vLLM-Omni /v1/audio/speech URL (FFI fallback).",
    ),
    ffmpeg: str = typer.Option("ffmpeg", "--ffmpeg", help="ffmpeg binary path."),
) -> None:
    """Locate Qwen3-TTS talker+codec GGUF + the qwentts.cpp FFI lib, write config.

    Run once after fetching the model weights (``scripts/fetch_model.sh``).
    Writes ``~/.qwenvoice/config.yml``.
    """
    table = Table(title="QwenVoice init — artifact scan", show_lines=False)
    table.add_column("artifact", style="cyan")
    table.add_column("status", style="green")
    table.add_column("path")

    # talker GGUF
    talker_ok = talker.exists()
    table.add_row(
        "talker GGUF",
        "ok" if talker_ok else "MISSING",
        str(talker),
    )

    # codec GGUF — auto-discover sibling *tokenizer*.gguf if not given.
    if codec is None:
        discovered = discover_codec_gguf(talker)
        codec = Path(discovered) if discovered else Path("qwen-tokenizer-12hz-Q8_0.gguf")
    codec_ok = codec.exists()
    table.add_row(
        "codec/tokenizer GGUF",
        "ok" if codec_ok else "MISSING",
        str(codec),
    )

    # FFI lib — auto-detect if not given.
    ffi_str = str(ffi_lib) if ffi_lib else ""
    if not ffi_str:
        # mirror synth._discover_ffi_lib but keep it shallow here for init output
        for d in (".", "/usr/local/lib", "/usr/lib", "/opt/homebrew/lib"):
            import glob

            for pat in ("libgoqwen3ttscpp*.so", "libgoqwen3ttscpp*.dylib"):
                hits = glob.glob(str(Path(d) / pat))
                if hits:
                    ffi_str = hits[0]
                    break
            if ffi_str:
                break
    ffi_ok = bool(ffi_str and Path(ffi_str).exists())
    table.add_row(
        "qwentts.cpp FFI lib",
        "ok" if ffi_ok else "MISSING (HTTP fallback)",
        ffi_str or "(auto-detect failed)",
    )

    # ffmpeg
    ffmpeg_ok = shutil.which(ffmpeg) is not None
    table.add_row("ffmpeg", "ok" if ffmpeg_ok else "MISSING", ffmpeg)

    console.print(table)

    cfg = QwenVoiceConfig(
        talker_gguf=str(talker),
        codec_gguf=str(codec),
        ffi_lib_path=ffi_str,
        http_fallback_url=http_fallback,
        ffmpeg_bin=ffmpeg,
    )
    cfg.save(DEFAULT_CONFIG_PATH)
    console.print(f"\n[green]wrote[/green] {DEFAULT_CONFIG_PATH}")

    if not (talker_ok and codec_ok):
        err_console.print(
            "[yellow]hint:[/yellow] run [cyan]scripts/fetch_model.sh[/cyan] to "
            "download the talker+codec GGUF, then re-run [cyan]qwenvoice init[/cyan]."
        )
    if not ffi_ok and not http_fallback:
        err_console.print(
            "[yellow]hint:[/yellow] no FFI lib and no HTTP fallback — synthesis will "
            "fail. Build qwentts.cpp or start a local vLLM-Omni server."
        )


# ---------------------------------------------------------------------------
# say — m1: single-segment synth (FULLY IMPLEMENTED)
# ---------------------------------------------------------------------------
@app.command()
def say(
    voice: Path = typer.Option(..., "--voice", "-v", help="Speaker reference audio (WAV/MP3, >=5s)."),
    ref_text: str = typer.Option(..., "--ref-text", "-r", help="Transcript of the reference audio."),
    text: str = typer.Option(..., "--text", "-t", help="Text to synthesize (one segment)."),
    out: Path = typer.Option(Path("out.mp3"), "--out", "-o", help="Output MP3 path."),
    talker: Path = typer.Option(None, "--talker", help="Override talker GGUF (else config)."),
    codec: Path = typer.Option(None, "--codec", help="Override codec GGUF (else config)."),
    ffi_lib: str = typer.Option("", "--ffi-lib", help="Override qwentts.cpp FFI lib path."),
    seed: int = typer.Option(42, "--seed", help="Fixed seed for the voice lock."),
) -> None:
    """m1 — synthesize ONE segment with a locked cloned voice → MP3.

    Locks the speaker reference + its transcript + the Qwen3-TTS talker/codec
    GGUF, synthesizes ``--text`` via the qwentts.cpp FFI (qt3_load+qt3_tts),
    and renders the result to ``--out`` as MP3. The voice biometric never
    leaves the machine.

    \b
    Example:
      qwenvoice say --voice mom.wav --ref-text "今天天气真好" \\
        --text "你好，欢迎使用 QwenVoice。" -o hello.mp3
    """
    cfg = QwenVoiceConfig.load()
    talker_path = talker or Path(cfg.talker_gguf)
    codec_path = codec or Path(cfg.codec_gguf)
    if ffi_lib:
        cfg.ffi_lib_path = ffi_lib
    cfg.seed = seed

    console.print("[cyan]locking voice...[/cyan]")
    try:
        lock = VoiceLock.lock(
            speaker_ref_path=voice,
            ref_text=ref_text,
            talker_gguf=talker_path,
            codec_gguf=codec_path,
            ffi_lib_path=cfg.ffi_lib_path,
            seed=seed,
        )
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]voice lock failed:[/red] {exc}")
        raise typer.Exit(code=2) from None

    console.print(f"[dim]voice lock: {lock.ref_hash}[/dim]")

    # m1 = single segment. segment_single keeps the m1/m2 surface uniform.
    segments = segment_single(text)
    seg = segments[0]
    console.print(f"[cyan]synthesizing 1 segment ({len(seg.text)} chars)...[/cyan]")

    with console.status("[bold green]synthesizing via qwentts.cpp FFI…[/bold green]"):
        try:
            pcm = synth_segment(lock, seg.text, cfg)
        except SynthesisError as exc:
            err_console.print(f"[red]synthesis failed:[/red] {exc}")
            err_console.print(
                "[dim]hint: ensure libgoqwen3ttscpp is built/loadable, or set "
                "--http-fallback to a local vLLM-Omni server.[/dim]"
            )
            raise typer.Exit(code=3) from None

    console.print(f"[cyan]rendering MP3 → {out}...[/cyan]")
    rendered = render_segment_with_text(pcm, seg.id, seg.text, out.parent if out.parent != Path("") else Path("."))
    # render_segment_with_text writes seg_NNN.mp3 into out.parent; for `say` we
    # honor the explicit --out name by renaming if they differ.
    final = Path(rendered.audio_path)
    desired = Path(out)
    if desired != final:
        desired.parent.mkdir(parents=True, exist_ok=True)
        final.rename(desired)
        final = desired
    console.print(f"[green]done[/green] → {final}")
    console.print(f"[dim]ref_hash={lock.ref_hash} seed={seed}[/dim]")


# ---------------------------------------------------------------------------
# book — m2: long-text segmentation + multi-segment narration (STUB)
# ---------------------------------------------------------------------------
@app.command()
def book(
    voice: Path = typer.Option(..., "--voice", "-v", help="Speaker reference audio."),
    ref_text: str = typer.Option(..., "--ref-text", "-r", help="Reference transcript."),
    file: Path = typer.Option(..., "--file", "-f", help="Long Chinese text file."),
    out: Path = typer.Option(Path("book"), "--out", "-o", help="Output dir for seg_NNN.mp3 + full.mp3."),
    seed: int = typer.Option(42, "--seed", help="Fixed seed for the voice lock."),
) -> None:
    """m2 — segment long Chinese text, synth each with the locked voice, concat.

    Produces ``book/seg_001.mp3 .. seg_NNN.mp3`` + concatenated ``book/full.mp3``
    + ``book/manifest.json``. The VoiceLock + per-segment seed guarantee that
    redrawing any one segment later leaves the others byte-identical.
    """
    # TODO(m2): wire segment_long_text → synth_segment per segment →
    # render_segment_with_text → concatenate_segments → NarrationManifest.write.
    # The primitives (segment.py, synth.py, render.py, manifest.py) are all in
    # place from m1; m2 is the multi-segment orchestration loop + rich progress.
    err_console.print(
        "[yellow]book is the m2 milestone and is not implemented in this build.[/yellow]"
    )
    err_console.print(
        "[dim]m1 (`qwenvoice say`) is fully implemented — use it for single-segment "
        "synthesis. See the roadmap in README.md.[/dim]"
    )
    raise typer.Exit(code=64)


# ---------------------------------------------------------------------------
# redraw — m3: per-segment redraw without changing the voice lock (STUB)
# ---------------------------------------------------------------------------
@app.command()
def redraw(
    book_dir: Path = typer.Option(..., "--book", help="Narration dir with manifest.json."),
    seg: int = typer.Option(..., "--seg", help="Segment id to redraw (1-indexed)."),
    text: str = typer.Option(..., "--text", help="New text for the segment."),
) -> None:
    """m3 — redraw ONE segment with edited text, voice lock + others untouched.

    Reads ``<book>/manifest.json``, re-synthesizes only ``--seg`` with the
    existing VoiceLock + the new ``--text``, overwrites only ``seg_NNN.mp3``.
    Every other segment's bytes stay identical — the moat demo.
    """
    # TODO(m3): NarrationManifest.load(book_dir) → verify lock_matches →
    # synth_segment(lock, new_text) → render_segment_with_text overwrite →
    # manifest.mark_redrawn + write. The contract is enforced by VoiceLock
    # (ref_hash unchanged → voice unchanged) + render (byte-stable mp3).
    err_console.print(
        "[yellow]redraw is the m3 milestone and is not implemented in this build.[/yellow]"
    )
    err_console.print(
        "[dim]The VoiceLock + manifest primitives that make redraw enforceable are "
        "in place from m1/m2; m3 is the redraw wiring + the byte-stability check.[/dim]"
    )
    raise typer.Exit(code=64)


if __name__ == "__main__":
    sys.exit(app())
