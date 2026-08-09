"""3-line programmatic example — synthesize one segment with a locked voice.

    from qwenvoice.config import QwenVoiceConfig
    from qwenvoice.voice import VoiceLock
    from qwenvoice.synth import synth_segment
    from qwenvoice.render import render_segment_with_text

    cfg = QwenVoiceConfig.load()
    lock = VoiceLock.lock(speaker_ref_path="mom.wav", ref_text="今天天气真好",
                          talker_gguf=cfg.talker_gguf, codec_gguf=cfg.codec_gguf)
    pcm = synth_segment(lock, "你好，欢迎使用 QwenVoice。", cfg)
    render_segment_with_text(pcm, seg_id=1, text="你好，欢迎使用 QwenVoice。", output_dir=".")
"""

from qwenvoice.config import QwenVoiceConfig
from qwenvoice.render import render_segment_with_text
from qwenvoice.synth import synth_segment
from qwenvoice.voice import VoiceLock


def main() -> None:
    cfg = QwenVoiceConfig.load()
    lock = VoiceLock.lock(
        speaker_ref_path="mom.wav",
        ref_text="今天天气真好",
        talker_gguf=cfg.talker_gguf,
        codec_gguf=cfg.codec_gguf,
    )
    pcm = synth_segment(lock, "你好，欢迎使用 QwenVoice。", cfg)
    rendered = render_segment_with_text(
        pcm, seg_id=1, text="你好，欢迎使用 QwenVoice。", output_dir="."
    )
    print(f"done -> {rendered.audio_path}")


if __name__ == "__main__":
    main()
