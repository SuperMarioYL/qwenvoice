"""QwenVoice CLI — typer surface for ``say`` / ``book`` / ``redraw`` / ``init``.

``say`` synthesizes one segment with a locked voice; ``book`` segments a long
Chinese text and narrates every segment through the same lock (seg_NNN.mp3 +
full.mp3 + manifest.json); ``redraw`` re-synthesizes a single manifest segment
with edited text, leaving every other file untouched.

Examples::

    qwenvoice init
    qwenvoice say --voice mom.wav --ref-text "今天天气真好" --text "你好，欢迎使用 QwenVoice。" -o hello.mp3
    qwenvoice book --voice mom.wav --ref-text "今天天气真好" --file novel.txt -o book/
    qwenvoice redraw book/ --seg 2 --text "改写后的第二句。"
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import DEFAULT_CONFIG_PATH, QwenVoiceConfig, discover_codec_gguf
from .manifest import FULL_AUDIO_FILENAME, NarrationManifest
from .render import concatenate_segments, render_segment_with_text
from .segment import segment_long_text, segment_single
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
# shared error surfaces — every command exits with a friendly message, never
# a raw traceback, for the failure modes a user can actually hit.
# ---------------------------------------------------------------------------
def _load_config_or_exit() -> QwenVoiceConfig:
    """Load ~/.qwenvoice/config.yml, exiting friendly if it is malformed.

    A hand-edited or truncated config.yml must not escape as a raw
    yaml/pydantic traceback (v0.3.0 fix: both used to, exit code 1).
    """
    try:
        return QwenVoiceConfig.load(DEFAULT_CONFIG_PATH)
    except (yaml.YAMLError, ValidationError) as exc:
        err_console.print(f"[red]config error:[/red] {DEFAULT_CONFIG_PATH}: {exc}")
        err_console.print(
            "[dim]hint: fix or delete the file, then re-run `qwenvoice init`.[/dim]"
        )
        raise typer.Exit(code=2) from None


def _render_error(exc: Exception) -> None:
    """Friendly exit for MP3 render failures (missing ffmpeg is the usual cause)."""
    err_console.print(f"[red]render failed:[/red] {type(exc).__name__}: {exc}")
    err_console.print(
        "[dim]hint: MP3 rendering shells out to ffmpeg/ffprobe — install ffmpeg "
        "(e.g. `brew install ffmpeg` or `apt-get install ffmpeg`) and retry.[/dim]"
    )
    raise typer.Exit(code=4) from None


def _synthesis_error(exc: SynthesisError, on: str = "") -> None:
    """Friendly exit for synthesis failures (shared by say / book / redraw)."""
    label = f" on segment {on}" if on else ""
    err_console.print(f"[red]synthesis failed{label}:[/red] {exc}")
    err_console.print(
        "[dim]hint: ensure libgoqwen3ttscpp is built/loadable, or set "
        "http_fallback_url (qwenvoice init --http-fallback) to a local "
        "vLLM-Omni server.[/dim]"
    )
    raise typer.Exit(code=3) from None


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
    cfg = _load_config_or_exit()
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
            _synthesis_error(exc)

    console.print(f"[cyan]rendering MP3 → {out}...[/cyan]")
    try:
        # render_segment_with_text writes seg_NNN.mp3 into out.parent; for `say`
        # we honor the explicit --out name by renaming if they differ.
        rendered = render_segment_with_text(pcm, seg.id, seg.text, out.parent)
    except Exception as exc:
        _render_error(exc)
    final = Path(rendered.audio_path)
    desired = Path(out)
    if desired != final:
        desired.parent.mkdir(parents=True, exist_ok=True)
        final.rename(desired)
        final = desired
    console.print(f"[green]done[/green] → {final}")
    console.print(f"[dim]ref_hash={lock.ref_hash} seed={seed}[/dim]")


# ---------------------------------------------------------------------------
# book — m2: long-text segmentation + multi-segment narration (IMPLEMENTED v0.3.0)
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
    cfg = _load_config_or_exit()
    if not file.exists():
        err_console.print(f"[red]input file not found:[/red] {file}")
        raise typer.Exit(code=2) from None
    text = file.read_text(encoding="utf-8")

    console.print("[cyan]locking voice...[/cyan]")
    try:
        lock = VoiceLock.lock(
            speaker_ref_path=voice,
            ref_text=ref_text,
            talker_gguf=Path(cfg.talker_gguf),
            codec_gguf=Path(cfg.codec_gguf),
            ffi_lib_path=cfg.ffi_lib_path,
            seed=seed,
        )
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]voice lock failed:[/red] {exc}")
        raise typer.Exit(code=2) from None
    console.print(f"[dim]voice lock: {lock.ref_hash}[/dim]")

    try:
        segments = segment_long_text(text, cfg.max_chars_per_segment)
    except ValueError as exc:
        err_console.print(f"[red]segmentation failed:[/red] {exc}")
        raise typer.Exit(code=2) from None

    manifest = NarrationManifest.from_lock(
        lock, segment_texts=[seg.text for seg in segments], output_dir=out
    )
    total = len(manifest.segments)
    console.print(f"[cyan]narrating {total} segments → {out}...[/cyan]")

    rendered_paths: list[Path] = []
    for seg in manifest.segments:
        console.print(
            f"[cyan]synthesizing segment {seg.id}/{total} ({len(seg.text)} chars)...[/cyan]"
        )
        try:
            pcm = synth_segment(lock, seg.text, cfg)
        except SynthesisError as exc:
            _synthesis_error(exc, on=str(seg.id))
        try:
            rendered = render_segment_with_text(pcm, seg.id, seg.text, out)
        except Exception as exc:
            _render_error(exc)
        seg.status = "synthesized"
        rendered_paths.append(Path(rendered.audio_path))

    try:
        full_path = concatenate_segments(rendered_paths, Path(out) / FULL_AUDIO_FILENAME)
    except Exception as exc:
        _render_error(exc)
    manifest.write()
    console.print(
        f"[green]done[/green] → {manifest.manifest_path}: {total} segments + {Path(full_path).name}"
    )
    console.print(f"[dim]ref_hash={lock.ref_hash} seed={lock.seed}[/dim]")


# ---------------------------------------------------------------------------
# redraw — m3: per-segment redraw without changing the voice lock (IMPLEMENTED v0.3.0)
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
    Every other segment's bytes stay identical — the moat demo. A reference
    that was re-recorded (lock hash drift) is refused: a redraw changes text,
    never voice.
    """
    cfg = _load_config_or_exit()
    try:
        manifest = NarrationManifest.load(book_dir)
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]redraw failed:[/red] {exc}")
        raise typer.Exit(code=2) from None
    try:
        manifest.get_segment(seg)
    except KeyError:
        err_console.print(
            f"[red]redraw failed:[/red] segment id {seg} not in manifest "
            f"({len(manifest.segments)} segments: seg_001.."
            f"seg_{len(manifest.segments):03d})."
        )
        raise typer.Exit(code=2) from None
    if not text.strip():
        err_console.print("[red]redraw failed:[/red] --text must be non-empty.")
        raise typer.Exit(code=2) from None

    # Rebuild the lock from the manifest's pinned artifacts — deriving ref_hash
    # from the on-disk reference is what lets lock_matches detect re-records.
    try:
        lock = VoiceLock.lock(
            speaker_ref_path=manifest.voice.speaker_ref_path,
            ref_text=manifest.voice.ref_text,
            talker_gguf=manifest.voice.talker_gguf,
            codec_gguf=manifest.voice.codec_gguf,
            ffi_lib_path=manifest.voice.ffi_lib_path,
            seed=manifest.voice.seed,
        )
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]voice lock failed:[/red] {exc}")
        raise typer.Exit(code=2) from None
    if not manifest.lock_matches(lock):
        err_console.print(
            "[red]redraw refused:[/red] the reference audio or transcript changed "
            "since the manifest was written — redrawing would change the voice, "
            "not just the text. Re-run `qwenvoice book` to create a new lock."
        )
        raise typer.Exit(code=2) from None
    # Honor the pinned artifacts over the current config so the redraw uses the
    # same synthesis setup the book was made with.
    if manifest.voice.ffi_lib_path:
        cfg.ffi_lib_path = manifest.voice.ffi_lib_path

    console.print(f"[cyan]redrawing segment {seg}...[/cyan]")
    try:
        pcm = synth_segment(lock, text, cfg)
    except SynthesisError as exc:
        _synthesis_error(exc, on=str(seg))
    try:
        rendered = render_segment_with_text(pcm, seg, text, book_dir)
    except Exception as exc:
        _render_error(exc)
    manifest.mark_redrawn(seg, text)
    manifest.write()
    console.print(
        f"[green]done[/green] → {rendered.audio_path} "
        f"(voice lock {lock.ref_hash}, other segments untouched)"
    )


if __name__ == "__main__":
    sys.exit(app())
