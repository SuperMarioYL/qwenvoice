"""Use the real text segmenter without audio/model artifacts."""
import json
from dataclasses import asdict
from qwenvoice.segment import segment_long_text
text = "缓存保存可复用的结果。数据变化后需要失效。接下来，为每类数据选择有效期。"
segments = segment_long_text(text, max_chars_per_segment=18)
print(json.dumps({"input":text,"soft_limit":18,"segments":[asdict(s) for s in segments]},ensure_ascii=False,indent=2))
print("Input preserved:", "".join(s.text for s in segments) == text)
print("Scope: sentence-boundary text segmentation only; no voice cloning or audio synthesis.")
