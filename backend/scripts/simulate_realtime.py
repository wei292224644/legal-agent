"""
模拟 800ms 实时推流：将音频切成 800ms 块，逐块送入 pipeline，观察响应时延。

用法:
    uv run python scripts/simulate_realtime.py --conv path/to/audio.wav [--lawyer path/to/lawyer.wav]
    uv run python scripts/simulate_realtime.py --conv scripts/对话录音.wav
"""

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

CHUNK_MS = 800
SR = 16000
CHUNK_SAMPLES = int(CHUNK_MS * SR / 1000)   # 12800 samples per chunk


def load_audio_16k(path: str) -> np.ndarray:
    import soundfile as sf
    import soxr

    audio, sr = sf.read(path, always_2d=True)
    audio = audio.mean(axis=1)
    if sr != 16000:
        audio = soxr.resample(audio, sr, 16000)
    return audio.astype(np.float32)


def audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio, SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


async def run(conv_path: str, lawyer_path: str | None, session_id: str) -> None:
    import voiceprint
    from audio_pipeline import AudioPipeline
    # Real-time streaming uses v1 (per-segment voiceprint comparison).
    # V2's ClusterBackend(oracle_num=2) is a batch algorithm that needs
    # all audio upfront; it's used via validate_pipeline_v2.py for offline
    # processing of complete recordings.

    if lawyer_path:
        print(f"[声纹] 注册: {lawyer_path}")
        voiceprint.register(audio_to_wav_bytes(load_audio_16k(lawyer_path)), session_id)

    audio = load_audio_16k(conv_path)
    duration = len(audio) / SR
    lawyer_vp = voiceprint.load(session_id) if lawyer_path else None

    print(f"[音频] {conv_path}  时长={duration:.1f}s")
    print(f"[配置] chunk={CHUNK_MS}ms  共 {len(audio) // CHUNK_SAMPLES + 1} 块")
    print(f"[提示] 首次加载模型需要几秒，之后每块应该很快\n")

    pipeline = AudioPipeline(lawyer_voiceprint=lawyer_vp)

    # 切块并逐块推入
    chunks = [
        audio[i : i + CHUNK_SAMPLES]
        for i in range(0, len(audio), CHUNK_SAMPLES)
    ]

    wall_start = time.time()
    total_results = 0

    for idx, chunk in enumerate(chunks):
        chunk_start_s = idx * CHUNK_MS / 1000
        t0 = time.time()
        results = await pipeline.process_segment(chunk)
        latency = (time.time() - t0) * 1000

        wall_elapsed = time.time() - wall_start
        label = f"[{chunk_start_s:6.1f}s]"

        if results:
            for r in results:
                speaker_tag = {"律师": "🧑‍⚖️", "客户": "👤", "未知": "❓"}.get(r.speaker, r.speaker)
                print(f"{label}  ✅ {latency:5.0f}ms  {speaker_tag} {r.speaker}: {r.text}")
                total_results += 1
        else:
            # 每 5 个空块打一行，避免刷屏
            if idx % 5 == 0:
                print(f"{label}  ·· {latency:5.0f}ms  (无输出)")

    total_elapsed = time.time() - wall_start
    print(f"\n{'─'*60}")
    print(f"  音频时长: {duration:.1f}s  |  实际耗时: {total_elapsed:.1f}s  |  共 {total_results} 句转写")
    print(f"  实时倍率: {duration / total_elapsed:.1f}x  (>1 = 快于实时)")
    print(f"{'─'*60}")


def main():
    parser = argparse.ArgumentParser(description="800ms 实时推流模拟")
    parser.add_argument("--conv",    required=True)
    parser.add_argument("--lawyer",  default=None)
    parser.add_argument("--session", default="demo")
    args = parser.parse_args()

    for p in [args.conv, args.lawyer]:
        if p and not Path(p).exists():
            print(f"错误: 找不到文件 → {p}")
            sys.exit(1)

    asyncio.run(run(args.conv, args.lawyer, args.session))


if __name__ == "__main__":
    main()
