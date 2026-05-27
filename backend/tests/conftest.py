"""按需生成测试 fixture WAV(从主 WAV 里切 / 合成),首跑后缓存。

避免把二进制 fixture 文件 commit 进 git。
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from tests.streaming_fixtures import (
    FIXTURE_DIR,
    LONG_MONOLOGUE_WAV,
    MAIN_WAV,
    SHORT_CLIENT_WAV,
    SHORT_LAWYER_WAV,
    TWO_UTTERANCES_WAV,
)

SR = 16000


@pytest.fixture(scope="session", autouse=True)
def _preload_models():
    """启动时预加载 FunASR 模型,避免延迟测试把 lazy load 算进去。

    模拟生产环境"服务启动即模型就绪"的语义。
    """
    from stt.funasr_stream import _get_models  # noqa: PLC0415

    _get_models()


def _load_main() -> np.ndarray:
    audio, sr = sf.read(str(MAIN_WAV), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    assert sr == SR, f"main WAV must be {SR}Hz, got {sr}"
    return audio


@pytest.fixture(scope="session", autouse=True)
def _ensure_fixtures():
    """启动时确保三个 fixture WAV 存在;不存在则从主 WAV 生成。"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    if not SHORT_CLIENT_WAV.exists():
        audio = _load_main()
        # 脚本 L1 是客户开场(王律师你好...),前 14s 覆盖完整一句
        sf.write(str(SHORT_CLIENT_WAV), audio[: 14 * SR], SR, subtype="PCM_16")

    if not SHORT_LAWYER_WAV.exists():
        audio = _load_main()
        # 脚本 L3 是律师回应,大约从 14s 开始,取 14-28s
        sf.write(str(SHORT_LAWYER_WAV), audio[14 * SR : 28 * SR], SR, subtype="PCM_16")

    if not TWO_UTTERANCES_WAV.exists():
        audio = _load_main()
        # 合成: 前 5s 真音频 + 3s 静默 + 14-19s 真音频
        # 静默时长选 3s > VAD 阈值 1.5s,确保两段被切分
        silence = np.zeros(3 * SR, dtype=np.float32)
        seg_a = audio[: 5 * SR]
        seg_b = audio[14 * SR : 19 * SR]
        synth = np.concatenate([seg_a, silence, seg_b])
        sf.write(str(TWO_UTTERANCES_WAV), synth, SR, subtype="PCM_16")

    if not LONG_MONOLOGUE_WAV.exists():
        audio = _load_main()
        # 合成: 9s 真音频 + 0.4s 静默 + 3s 真音频
        # 0.4s < 1.5s VAD 阈值(不应被 VAD 切),但 ≥ 0.3s 微停顿(soft cap 应在此处切)
        # 9s > 8s soft cap → 累计 8s 后进入"等下一个微停顿"状态
        silence = np.zeros(int(0.4 * SR), dtype=np.float32)
        seg_a = audio[: 9 * SR]
        seg_b = audio[14 * SR : 17 * SR]
        synth = np.concatenate([seg_a, silence, seg_b])
        sf.write(str(LONG_MONOLOGUE_WAV), synth, SR, subtype="PCM_16")
