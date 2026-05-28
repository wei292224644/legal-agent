"""按真实时间节奏喂数据的共享 fixture。

Sprint 1 只用到 stream_wav_realtime;后续模块会再加 stream_script_realtime。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import soundfile as sf


async def stream_wav_realtime(
    path: str | Path,
    chunk_ms: int = 100,
    speed: float = 1.0,
) -> AsyncIterator[tuple[np.ndarray, float]]:
    """按真实时间节奏 yield 音频块。

    Args:
        path: WAV 文件,期望 16kHz mono PCM
        chunk_ms: 每块时长(毫秒)
        speed: 加速倍数(>1 加快,用于离线 CI)。1.0 = 真实时间。

    Yields:
        (pcm_chunk: float32 [-1,1] 单通道, relative_seconds: 自起点的相对秒)
    """
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"expected 16kHz, got {sr}Hz at {path}")

    chunk_samples = int(sr * chunk_ms / 1000)
    interval = (chunk_ms / 1000) / speed

    t0 = time.monotonic()
    for i in range(0, len(audio), chunk_samples):
        target = t0 + (i // chunk_samples) * interval
        sleep = target - time.monotonic()
        if sleep > 0:
            await asyncio.sleep(sleep)
        yield audio[i : i + chunk_samples], time.monotonic() - t0


FIXTURE_DIR = Path(__file__).parent / "fixtures"

MAIN_WAV = FIXTURE_DIR / "劳动仲裁对话_完整版.wav"
VOICEPRINT_WAV = FIXTURE_DIR / "律师声纹注册.wav"
SCRIPT_MD = FIXTURE_DIR / "劳动仲裁对话脚本_角色话版.md"

SHORT_CLIENT_WAV = FIXTURE_DIR / "short_client.wav"
SHORT_LAWYER_WAV = FIXTURE_DIR / "short_lawyer.wav"
TWO_UTTERANCES_WAV = FIXTURE_DIR / "two_utterances.wav"
LONG_MONOLOGUE_WAV = FIXTURE_DIR / "long_monologue.wav"
