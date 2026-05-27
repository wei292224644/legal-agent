"""
端到端验证脚本：注册律师声纹 → 转写对话 → 打角色标签

用法:
    # 完整流程（有律师声纹）
    uv run python scripts/validate_pipeline.py \
        --conv   path/to/conversation.wav \
        --lawyer path/to/lawyer_sample.wav

    # 仅测试 STT + 说话人分离（无声纹）
    uv run python scripts/validate_pipeline.py \
        --conv path/to/conversation.wav

支持格式: WAV / MP3 / M4A / FLAC（任意采样率，自动重采样至 16kHz mono）
"""

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Audio loading ─────────────────────────────────────────────────────────────

def load_audio_16k(path: str) -> np.ndarray:
    """Load any audio file → float32 mono numpy array at 16 kHz."""
    import soundfile as sf
    import soxr

    audio, sr = sf.read(path, always_2d=True)   # (samples, channels)
    audio = audio.mean(axis=1)                   # stereo → mono
    if sr != 16000:
        audio = soxr.resample(audio, sr, 16000)
    return audio.astype(np.float32)


def audio_to_wav_bytes(audio: np.ndarray, sr: int = 16000) -> bytes:
    """Encode float32 numpy array to 16-bit PCM WAV bytes."""
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(conv_path: str, lawyer_path: str | None, session_id: str) -> None:
    import voiceprint
    from audio_pipeline import AudioPipeline

    # ── Step 1: 注册律师声纹 ─────────────────────────────────────────────────
    if lawyer_path:
        print(f"\n[1/3] 注册律师声纹: {lawyer_path}")
        lawyer_audio = load_audio_16k(lawyer_path)
        wav_bytes = audio_to_wav_bytes(lawyer_audio)
        voiceprint.register(wav_bytes, session_id)
        print(f"      ✅ 声纹已保存 → voiceprints/{session_id}.npy")
    else:
        print("\n[1/3] 未提供律师声纹，说话人角色将默认标为「客户」")

    # ── Step 2: 加载对话音频 ─────────────────────────────────────────────────
    print(f"\n[2/3] 加载对话音频: {conv_path}")
    conv_audio = load_audio_16k(conv_path)
    duration = len(conv_audio) / 16000
    print(f"      时长: {duration:.1f}s  |  采样点: {len(conv_audio):,}")

    lawyer_vp = voiceprint.load(session_id) if lawyer_path else None

    # ── Step 3: 运行 pipeline ────────────────────────────────────────────────
    print("\n[3/3] 运行 funASR pipeline（首次运行会下载模型，约需几分钟）...")
    t0 = time.time()
    pipeline = AudioPipeline(lawyer_voiceprint=lawyer_vp)  # hub='hf' 已在 src 内硬编码
    results = await pipeline.process_segment(conv_audio)
    elapsed = time.time() - t0

    # ── 输出结果 ─────────────────────────────────────────────────────────────
    if not results:
        print("\n⚠️  pipeline 未返回任何结果（可能是静音或音频质量问题）")
        return

    print(f"\n{'─'*60}")
    print(f"  转写结果（共 {len(results)} 句，耗时 {elapsed:.1f}s）")
    print(f"{'─'*60}")
    for i, r in enumerate(results, 1):
        label = {
            "律师": "🧑‍⚖️ 律师",
            "客户": "👤 客户",
            "未知": "❓ 未知",
        }.get(r.speaker, r.speaker)
        print(f"  [{i:02d}] {label}：{r.text}")
    print(f"{'─'*60}\n")


def main():
    parser = argparse.ArgumentParser(description="funASR pipeline 端到端验证")
    parser.add_argument("--conv",   required=True, help="对话音频文件路径")
    parser.add_argument("--lawyer", default=None,  help="律师声纹音频（5~15s 单人片段）")
    parser.add_argument("--session", default="demo", help="session ID（默认: demo）")
    args = parser.parse_args()

    if not Path(args.conv).exists():
        print(f"错误: 找不到对话音频文件 → {args.conv}")
        sys.exit(1)
    if args.lawyer and not Path(args.lawyer).exists():
        print(f"错误: 找不到律师声纹文件 → {args.lawyer}")
        sys.exit(1)

    asyncio.run(run(args.conv, args.lawyer, args.session))


if __name__ == "__main__":
    main()
