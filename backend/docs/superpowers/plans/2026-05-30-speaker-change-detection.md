# Speaker Change Detection 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 VAD 合并后的长段内，用 cam++ 滑窗声纹比对检测说话人切换点，把跨说话人粘连的 utterance 切开。

**Architecture:** 纯新增三个文件，零改动现有文件。`speaker_change_detector.py` 实现三阶段滑窗 SCD 算法（lawyer-only → client seeding → dual comparison）；`funasr_stream_v2.py` 从 v1 import 共享工具，在 `merge_with_close_reason` 后插入 `_scd_split`；`bench_diarization.py` 顺序跑 v1/v2 并输出粘连对比报告。

**Tech Stack:** Python, NumPy, FunASR (cam++), 现有 enrollment/matcher/utterance 模型

---

## 文件映射

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/src/diarization/speaker_change_detector.py` | 创建 | SCD 核心：VoiceprintState + detect_speaker_changes |
| `backend/tests/test_speaker_change_detector.py` | 创建 | SCD 单元测试（mock embedding，覆盖三阶段+能量过滤+邻近合并） |
| `backend/src/stt/funasr_stream_v2.py` | 创建 | v2 STT 管线：从 v1 import 共享函数，插入 `_scd_split`，外部接口同 v1 |
| `backend/tests/test_funasr_stream_v2.py` | 创建 | v2 最小接口测试（签名一致 + 可导入运行） |
| `backend/bench_diarization.py` | 创建 | A/B 对比脚本：时间轴并排、粘连检测、汇总统计 |

---

## Task 1: SCD 骨架 — VoiceprintState + 空 detect_speaker_changes

**Files:**
- Create: `backend/src/diarization/speaker_change_detector.py`

- [ ] **Step 1: 创建骨架文件**

```python
"""Speaker Change Detection：对单段长音频滑窗提取 cam++ embedding，检测说话人切换点。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import SR
from diarization.voiceprint import extract_embedding


@dataclass
class VoiceprintState:
    """SCD 内部维护的动态声纹状态。"""

    lawyer: np.ndarray
    client: np.ndarray | None = None


def _ema_update(current: np.ndarray, new: np.ndarray, weight: float = 0.15) -> np.ndarray:
    """EMA 更新 client embedding，保持 L2 归一化。"""
    updated = current * (1 - weight) + new * weight
    norm = float(np.linalg.norm(updated))
    if norm > 0:
        updated = updated / norm
    return updated


def detect_speaker_changes(
    seg_audio: np.ndarray,
    voiceprint: VoiceprintState,
    sr: int = SR,
    window_ms: int = 1500,
    step_ms: int = 500,
    delta_threshold: float = 0.25,
    lawyer_threshold: float = 0.40,
    margin: float = 0.10,
) -> list[int]:
    """检测 seg_audio 内的说话人切换点，返回毫秒切分位置列表（相对 seg_audio 起点）。"""
    return []
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/diarization/speaker_change_detector.py
git commit -m "feat(scd): Speaker Change Detector 骨架"
```

---

## Task 2: SCD Phase 1 测试 + 实现（仅 lawyer 声纹的切换检测）

**Files:**
- Create: `backend/tests/test_speaker_change_detector.py`
- Modify: `backend/src/diarization/speaker_change_detector.py`

- [ ] **Step 1: 写 Phase 1 失败测试**

```python
"""Speaker Change Detector 单元测试。

所有测试 mock extract_embedding，避免加载 cam++ 模型。
"""

from __future__ import annotations

import numpy as np
import pytest

from diarization.speaker_change_detector import VoiceprintState, detect_speaker_changes


@pytest.fixture
def lawyer_emb() -> np.ndarray:
    return np.array([1.0, 0.0, 0.0], dtype=np.float32)


@pytest.fixture
def client_emb() -> np.ndarray:
    return np.array([0.0, 1.0, 0.0], dtype=np.float32)


def _make_fake_extractor(sequence: list[np.ndarray]):
    """按顺序返回 embedding 的 mock 工厂。"""
    idx = 0

    def fake_extract(audio: np.ndarray, sr: int) -> np.ndarray:
        nonlocal idx
        emb = sequence[idx]
        idx += 1
        return emb

    return fake_extract


def test_phase1_detects_lawyer_to_nonlawyer(monkeypatch, lawyer_emb):
    """阶段1：律师→非律师切换应被检测。"""
    from diarization import speaker_change_detector as scd

    nonlawyer = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    fake = _make_fake_extractor([lawyer_emb, lawyer_emb, nonlawyer, nonlawyer])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 4, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)

    assert len(changes) == 1
    assert changes[0] == 2000


def test_phase1_no_false_positive(monkeypatch, lawyer_emb):
    """阶段1：无跳变时不应误报切换。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb, lawyer_emb, lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 3, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)
    assert changes == []


def test_short_segment_returns_empty(monkeypatch, lawyer_emb):
    """短于 window_ms 的段直接返回空。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 1, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1500, step_ms=500)
    assert changes == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_speaker_change_detector.py -v`

Expected: 3 FAIL（`changes == []` 或 `len(changes) == 1` 不满足）

- [ ] **Step 3: 实现 Phase 1 算法**

在 `backend/src/diarization/speaker_change_detector.py` 中替换 `detect_speaker_changes` 的 `return []` 为完整实现：

```python
def detect_speaker_changes(
    seg_audio: np.ndarray,
    voiceprint: VoiceprintState,
    sr: int = SR,
    window_ms: int = 1500,
    step_ms: int = 500,
    delta_threshold: float = 0.25,
    lawyer_threshold: float = 0.40,
    margin: float = 0.10,
) -> list[int]:
    window_samples = int(sr * window_ms / 1000)
    step_samples = int(sr * step_ms / 1000)

    if len(seg_audio) < window_samples:
        return []

    embeddings: list[np.ndarray | None] = []
    window_starts_ms: list[int] = []

    for start in range(0, len(seg_audio) - window_samples + 1, step_samples):
        w = seg_audio[start : start + window_samples]
        energy = float(np.sqrt(np.mean(w.astype(np.float64) ** 2)))
        if energy < 0.001:
            embeddings.append(None)
        else:
            embeddings.append(extract_embedding(w, sr))
        window_starts_ms.append(int(start * 1000 / sr))

    n = len(embeddings)
    if n < 2:
        return []

    s_ls: list[float | None] = [None] * n
    for i, emb in enumerate(embeddings):
        if emb is not None:
            s_ls[i] = float(np.dot(emb, voiceprint.lawyer))

    changes_idx: list[int] = []
    prev_state: str | None = None
    prev_s: float | None = None
    seeded = voiceprint.client is not None

    for i in range(n):
        emb = embeddings[i]
        s_l = s_ls[i]
        if emb is None or s_l is None:
            continue

        if not seeded:
            cur_state = "lawyer" if s_l >= lawyer_threshold else "other"
        else:
            # Phase 3 placeholder for type consistency; seeded=False here
            cur_state = "other"

        if prev_state is not None and prev_state != cur_state and not seeded:
            if prev_s is not None and abs(prev_s - s_l) > delta_threshold:
                if (prev_s >= lawyer_threshold and s_l < lawyer_threshold) or (
                    prev_s < lawyer_threshold and s_l >= lawyer_threshold
                ):
                    changes_idx.append(i)
                    if prev_s > 0.50 and s_l < 0.20:
                        voiceprint.client = emb.copy()
                        seeded = True

        prev_state = cur_state
        prev_s = s_l

    result_ms: list[int] = []
    for idx in changes_idx:
        if idx == 0:
            continue
        split_ms = int(
            (window_starts_ms[idx - 1] + window_starts_ms[idx]) / 2 + window_ms / 2
        )
        result_ms.append(split_ms)

    if not result_ms:
        return []
    merged = [result_ms[0]]
    for cp in result_ms[1:]:
        if cp - merged[-1] < window_ms:
            continue
        merged.append(cp)
    return merged
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_speaker_change_detector.py -v`

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_speaker_change_detector.py backend/src/diarization/speaker_change_detector.py
git commit -m "feat(scd): Phase 1 仅 lawyer 声纹切换检测"
```

---

## Task 3: SCD Phase 2/3 + 能量过滤 + 邻近合并

**Files:**
- Modify: `backend/src/diarization/speaker_change_detector.py`
- Modify: `backend/tests/test_speaker_change_detector.py`

- [ ] **Step 1: 追加测试（写失败测试）**

在 `backend/tests/test_speaker_change_detector.py` 末尾追加：

```python
def test_phase2_seeding(monkeypatch, lawyer_emb, client_emb):
    """阶段2：高置信度 lawyer→非 lawyer 触发 client 种子化。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb, lawyer_emb, client_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 3, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)

    assert len(changes) == 1
    assert changes[0] == 2000
    assert vp.client is not None
    np.testing.assert_array_almost_equal(vp.client, client_emb)


def test_phase3_dual_flip(monkeypatch, lawyer_emb, client_emb):
    """阶段3：双声纹下 diff 正负翻检测切换。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([client_emb, client_emb, lawyer_emb, lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 4, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb, client=client_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)

    assert len(changes) == 1
    assert changes[0] == 2000


def test_skip_low_energy_window(monkeypatch, lawyer_emb):
    """能量 < 0.001 的静默窗口被跳过，不触发切换。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 2, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)
    assert changes == []


def test_merge_nearby_changes(monkeypatch, lawyer_emb, client_emb):
    """间距 < window_ms 的邻近切换点应合并去重。"""
    from diarization import speaker_change_detector as scd

    # 律师→客户→律师，step=500 时产生两个很近的切换点
    fake = _make_fake_extractor(
        [lawyer_emb, client_emb, lawyer_emb, lawyer_emb]
    )
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 4, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb, client=client_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1500, step_ms=500)

    # 默认 window_ms=1500，两个切换点间距 500ms < 1500ms，应合并为 1 个
    assert len(changes) == 1


def test_phase3_ema_update(monkeypatch, lawyer_emb, client_emb):
    """阶段3：高置信度 client 窗口触发 EMA 更新。"""
    from diarization import speaker_change_detector as scd

    # 4 个窗口全是 client（diff 很负），应触发 EMA
    fake = _make_fake_extractor([client_emb, client_emb, client_emb, client_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.zeros(16000 * 4, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb, client=client_emb.copy())
    original_client = vp.client.copy()
    detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)

    # EMA 更新后 client 应发生变化（但不等于新 embedding，因为是加权平均）
    assert vp.client is not None
    with pytest.raises(AssertionError):
        np.testing.assert_array_almost_equal(vp.client, original_client)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd backend && uv run pytest tests/test_speaker_change_detector.py -v`

Expected: 5 FAIL（Phase2/3/能量/合并/EMA 未实现）

- [ ] **Step 3: 补全算法（Phase2/3 + EMA + 能量 + 合并）**

将 `detect_speaker_changes` 中 `else:` 分支里的 `# Phase 3 placeholder` 替换为真实 Phase 3，并补全循环体：

```python
    for i in range(n):
        emb = embeddings[i]
        s_l = s_ls[i]
        if emb is None or s_l is None:
            continue

        if not seeded:
            cur_state = "lawyer" if s_l >= lawyer_threshold else "other"
        else:
            s_c = float(np.dot(emb, voiceprint.client))
            diff = s_l - s_c
            if diff > margin:
                cur_state = "lawyer"
            elif diff < -margin:
                cur_state = "client"
            else:
                cur_state = "uncertain"

        if prev_state is not None and prev_state != cur_state:
            if not seeded:
                if prev_s is not None and abs(prev_s - s_l) > delta_threshold:
                    if (prev_s >= lawyer_threshold and s_l < lawyer_threshold) or (
                        prev_s < lawyer_threshold and s_l >= lawyer_threshold
                    ):
                        changes_idx.append(i)
                        if prev_s > 0.50 and s_l < 0.20:
                            voiceprint.client = emb.copy()
                            seeded = True
            else:
                if {prev_state, cur_state} == {"lawyer", "client"}:
                    changes_idx.append(i)
                    s_c = float(np.dot(emb, voiceprint.client))
                    diff = s_l - s_c
                    if diff < -0.30:
                        voiceprint.client = _ema_update(voiceprint.client, emb, weight=0.15)

        prev_state = cur_state
        prev_s = s_l
```

其余代码（切分点计算、邻近合并）已在 Task 2 中实现，无需修改。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd backend && uv run pytest tests/test_speaker_change_detector.py -v`

Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_speaker_change_detector.py backend/src/diarization/speaker_change_detector.py
git commit -m "feat(scd): Phase 2/3 双声纹切换 + EMA + 能量过滤 + 邻近合并"
```

---

## Task 4: funasr_stream_v2 — 插入 SCD 拆分的 STT 管线

**Files:**
- Create: `backend/src/stt/funasr_stream_v2.py`
- Create: `backend/tests/test_funasr_stream_v2.py`

- [ ] **Step 1: 创建 v2 管线文件**

```python
"""FunASR 流式 STT 包装 V2。

与 v1 唯一区别：在 merge_with_close_reason 之后、ASR 之前插入 SCD 拆分。
从 v1 import 所有共享工具函数，避免重复。"""

from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator

import numpy as np

from config import SR, VAD_RECHECK_INTERVAL_MS, VAD_SILENCE_MS
from diarization.enrollment import Enrollment
from diarization.matcher import match_speaker
from diarization.speaker_change_detector import VoiceprintState, detect_speaker_changes
from models.utterance import ClosedBy, Utterance
from stt.funasr_stream import (
    _asr_one,
    _get_models,
    _utt_id,
    _vad_segments_ms,
    merge_with_close_reason,
)


def _scd_split(
    bounds: list[tuple[int, int, ClosedBy]],
    snapshot: np.ndarray,
    enrollment: Enrollment | None,
    voiceprint: VoiceprintState | None = None,
) -> list[tuple[int, int, ClosedBy]]:
    """对 bounds 中 ≥2s 的长段跑 SCD，按切换点拆成 sub-bounds。

    voiceprint 跨 bounds 共享，client 种子化后状态保持。
    """
    if enrollment is None:
        return bounds

    if voiceprint is None:
        voiceprint = VoiceprintState(lawyer=enrollment.embedding)

    sub_bounds: list[tuple[int, int, ClosedBy]] = []
    for s_ms, e_ms, closed_by in bounds:
        duration = e_ms - s_ms
        if duration < 2000:
            sub_bounds.append((s_ms, e_ms, closed_by))
            continue

        seg_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)]
        changes = detect_speaker_changes(seg_audio, voiceprint, sr=SR)

        if not changes:
            sub_bounds.append((s_ms, e_ms, closed_by))
            continue

        prev = s_ms
        for cp in changes:
            cp_abs = s_ms + cp
            if cp_abs - prev >= 500:
                sub_bounds.append((prev, cp_abs, "scd"))
                prev = cp_abs

        if e_ms - prev >= 500:
            sub_bounds.append((prev, e_ms, "scd"))
        else:
            # 丢弃末尾 <500ms 碎片，延长上一段
            if sub_bounds and sub_bounds[-1][2] == "scd":
                last_s, _, _ = sub_bounds[-1]
                sub_bounds[-1] = (last_s, e_ms, "scd")
            else:
                sub_bounds.append((prev, e_ms, closed_by))

    return sub_bounds


async def stream_stt_v2(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
    enrollment: Enrollment | None = None,
) -> AsyncIterator[Utterance]:
    """同 stream_stt，但在 ASR 前插入 Speaker Change Detection 拆分。"""
    vad_model, asr_model = _get_models()

    t0: float | None = None
    yielded_until_ms = 0
    last_vad_audio_ms = -VAD_RECHECK_INTERVAL_MS

    audio_buffer = array.array("f")
    spec_asr: dict[tuple[int, int], asyncio.Task] = {}

    voiceprint: VoiceprintState | None = None
    if enrollment is not None:
        voiceprint = VoiceprintState(lawyer=enrollment.embedding)

    def _spec_key_match(s_ms: int, e_ms: int, tol_ms: int = 100) -> tuple[int, int] | None:
        for k_s, k_e in spec_asr:
            if abs(k_s - s_ms) <= tol_ms and abs(k_e - e_ms) <= tol_ms:
                return (k_s, k_e)
        return None

    async def _emit_stable_or_final_v2(snapshot: np.ndarray, final: bool):
        nonlocal yielded_until_ms
        if len(snapshot) == 0:
            return
        total_ms = int(len(snapshot) * 1000 / SR)
        window_start_ms = max(0, yielded_until_ms - 500)
        window_start_sample = int(window_start_ms * SR / 1000)
        window_audio = snapshot[window_start_sample:]
        vad_out = await asyncio.to_thread(vad_model.generate, input=window_audio)
        raw_segs_rel = _vad_segments_ms(vad_out)
        raw_segs = [(s + window_start_ms, e + window_start_ms) for s, e in raw_segs_rel]
        bounds = merge_with_close_reason(raw_segs, snapshot)

        # V2 唯一改动：SCD 拆分
        sub_bounds = _scd_split(bounds, snapshot, enrollment, voiceprint)

        for s_ms, e_ms, closed_by in sub_bounds:
            if e_ms <= yielded_until_ms + 100:
                continue
            s_ms = max(s_ms, yielded_until_ms)
            silence_after_ms = total_ms - e_ms
            ready_to_spec = silence_after_ms >= 200 or final or closed_by == "soft_cap"
            if not ready_to_spec:
                continue

            matched_key = _spec_key_match(s_ms, e_ms)
            if matched_key is None:
                seg_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)].copy()
                spec_asr[(s_ms, e_ms)] = asyncio.create_task(_asr_one(asr_model, seg_audio))
                matched_key = (s_ms, e_ms)

            stable = final or closed_by == "soft_cap" or (silence_after_ms >= VAD_SILENCE_MS)
            if not stable:
                continue

            text = await spec_asr[matched_key]
            for k in list(spec_asr.keys()):
                if k[1] <= e_ms + 100:
                    spec_asr.pop(k, None)

            if not text:
                continue
            t_start = (t0 or 0.0) + s_ms / 1000.0
            t_end = (t0 or 0.0) + e_ms / 1000.0
            speaker = None
            if enrollment is not None:
                speaker_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)].copy()
                speaker = await asyncio.to_thread(match_speaker, speaker_audio, SR, enrollment)
            yield Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                speaker=speaker,
                closed_by=closed_by,
            )
            yielded_until_ms = max(yielded_until_ms, e_ms)

    async for chunk, t_rel in audio_chunks:
        if t0 is None:
            t0 = t_rel
        audio_buffer.frombytes(chunk.astype(np.float32).tobytes())
        total_ms = int(len(audio_buffer) * 1000 / SR)

        if total_ms - last_vad_audio_ms < VAD_RECHECK_INTERVAL_MS:
            continue
        last_vad_audio_ms = total_ms

        snapshot = np.array(audio_buffer, dtype=np.float32)
        async for utt in _emit_stable_or_final_v2(snapshot, final=False):
            yield utt

    snapshot = np.array(audio_buffer, dtype=np.float32)
    async for utt in _emit_stable_or_final_v2(snapshot, final=True):
        yield utt

    for task in spec_asr.values():
        if not task.done():
            task.cancel()
```

- [ ] **Step 2: 创建最小接口测试**

```python
"""funasr_stream_v2 最小测试：接口一致 + 可导入执行。"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from stt.funasr_stream import stream_stt
from stt.funasr_stream_v2 import stream_stt_v2


def test_stream_stt_v2_signature_matches_v1():
    """v2 外部接口必须与 v1 完全一致。"""
    sig_v1 = inspect.signature(stream_stt)
    sig_v2 = inspect.signature(stream_stt_v2)
    assert sig_v1 == sig_v2


@pytest.mark.asyncio
async def test_stream_stt_v2_empty_input():
    """空输入流不应产出任何 utterance，也不应抛异常。"""

    async def empty_chunks():
        if False:
            yield np.zeros(0, dtype=np.float32), 0.0

    utts = []
    async for utt in stream_stt_v2(empty_chunks(), enrollment=None):
        utts.append(utt)
    assert utts == []
```

- [ ] **Step 3: 运行测试**

Run: `cd backend && uv run pytest tests/test_funasr_stream_v2.py -v`

Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/stt/funasr_stream_v2.py tests/test_funasr_stream_v2.py
git commit -m "feat(stt): funasr_stream_v2 — SCD 拆分插入 merge 与 ASR 之间"
```

---

## Task 5: A/B 对比脚本 bench_diarization.py

**Files:**
- Create: `backend/bench_diarization.py`

- [ ] **Step 1: 创建脚本**

```python
#!/usr/bin/env python3
"""A/B 对比 v1 与 v2 STT 管线的说话人分割效果。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent / "src"))

from diarization.enrollment import enroll_speaker
from stt.funasr_stream import stream_stt
from stt.funasr_stream_v2 import stream_stt_v2


async def _chunk_iterator(
    audio: np.ndarray, sr: int, chunk_ms: int = 100
) -> AsyncIterator[tuple[np.ndarray, float]]:
    """无真实时间延迟的顺序 chunk 迭代器。"""
    chunk_samples = int(sr * chunk_ms / 1000)
    for i in range(0, len(audio), chunk_samples):
        yield audio[i : i + chunk_samples], i / sr


async def _run_pipeline(audio: np.ndarray, sr: int, enrollment, pipeline_fn):
    chunks = _chunk_iterator(audio, sr, chunk_ms=100)
    utts = []
    async for utt in pipeline_fn(chunks, enrollment=enrollment):
        utts.append(utt)
    return utts


def _load_audio(path: str) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr != 16000:
        raise ValueError(f"expected 16kHz, got {sr}Hz")
    return audio, sr


def _format_utt(utt) -> str:
    spk = utt.speaker or "N/A"
    return f"[{spk}] {utt.text[:50]}"


def _find_overlaps(utt, other_utts, tol_ms: float = 200.0):
    s, e = utt.t_start * 1000, utt.t_end * 1000
    overlaps = []
    for ou in other_utts:
        os_, oe = ou.t_start * 1000, ou.t_end * 1000
        if e + tol_ms < os_ or oe + tol_ms < s:
            continue
        overlaps.append(ou)
    return overlaps


def _detect_cross_speaker(utt, overlaps):
    if len(overlaps) < 2:
        return False
    speakers = {o.speaker for o in overlaps if o.speaker is not None}
    return len(speakers) >= 2


def main():
    parser = argparse.ArgumentParser(description="A/B 对比 v1/v2 diarization")
    parser.add_argument("--wav", required=True, help="输入 WAV 文件路径")
    parser.add_argument("--enrollment", required=True, help="律师声纹注册 WAV")
    args = parser.parse_args()

    audio, sr = _load_audio(args.wav)
    enroll_audio, enroll_sr = _load_audio(args.enrollment)
    enrollment = enroll_speaker(enroll_audio, enroll_sr)

    async def _run():
        print("=" * 70)
        print("Running V1 pipeline...")
        utts_v1 = await _run_pipeline(audio, sr, enrollment, stream_stt)
        print(f"  V1 产出 {len(utts_v1)} 条 utterance")

        print("Running V2 pipeline...")
        utts_v2 = await _run_pipeline(audio, sr, enrollment, stream_stt_v2)
        print(f"  V2 产出 {len(utts_v2)} 条 utterance")

        # 1. 时间轴并排表
        print("\n" + "=" * 70)
        print("Timeline comparison")
        print("-" * 70)
        all_events = []
        for u in utts_v1:
            all_events.append((u.t_start, u.t_end, "v1", u))
        for u in utts_v2:
            all_events.append((u.t_start, u.t_end, "v2", u))
        all_events.sort(key=lambda x: x[0])
        for s, e, ver, u in all_events:
            print(f"{ver:3} {s:7.2f}-{e:7.2f}s  {_format_utt(u)}")

        # 2. 粘连检测
        print("\n" + "=" * 70)
        print("Cross-speaker adhesion check (V1 as baseline)")
        print("-" * 70)
        cross_count = 0
        for u in utts_v1:
            overlaps = _find_overlaps(u, utts_v2)
            if _detect_cross_speaker(u, overlaps):
                cross_count += 1
                print(
                    f"  ⚠ V1 [{u.t_start:.2f}-{u.t_end:.2f}] {u.speaker} "
                    f"split into multiple V2 speakers:"
                )
                for o in overlaps:
                    print(
                        f"      V2 [{o.t_start:.2f}-{o.t_end:.2f}] {o.speaker}  {o.text[:40]}"
                    )
            elif len(overlaps) == 1 and overlaps[0].speaker != u.speaker:
                print(
                    f"  ! label mismatch V1={u.speaker} vs "
                    f"V2={overlaps[0].speaker} [{u.t_start:.2f}-{u.t_end:.2f}]"
                )

        # 3. 汇总统计
        def _stats(utts):
            lawyers = sum(1 for u in utts if u.speaker == "lawyer")
            clients = sum(1 for u in utts if u.speaker == "client")
            uncertain = sum(1 for u in utts if u.speaker == "uncertain")
            avg_dur = sum(u.t_end - u.t_start for u in utts) / max(len(utts), 1)
            scd = sum(1 for u in utts if u.closed_by == "scd")
            return len(utts), lawyers, clients, uncertain, avg_dur, scd

        n1, l1, c1, u1, d1, s1 = _stats(utts_v1)
        n2, l2, c2, u2, d2, s2 = _stats(utts_v2)

        print("\n" + "=" * 70)
        print("Summary")
        print("-" * 70)
        print(f"{'':20}  {'V1':>10}  {'V2':>10}")
        print(f"{'Utterances:':20}  {n1:>10}  {n2:>10}")
        print(f"{'Lawyer:':20}  {l1:>10}  {l2:>10}")
        print(f"{'Client:':20}  {c1:>10}  {c2:>10}")
        print(f"{'Uncertain:':20}  {u1:>10}  {u2:>10}")
        print(f"{'Avg duration:':20}  {d1:>10.1f}s  {d2:>10.1f}s")
        print(f"{'SCD splits:':20}  {s1:>10}  {s2:>10}")
        print(f"{'Cross-speaker (V1):':20}  {cross_count:>10}")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行 bench 脚本（功能验证，不要求结果完美）**

Run:
```bash
cd backend && uv run python bench_diarization.py \
  --wav tests/fixtures/劳动仲裁对话_完整版.wav \
  --enrollment tests/fixtures/律师声纹注册.wav
```

Expected: 脚本正常结束，打印 V1/V2 时间轴和 Summary，无异常 traceback。

- [ ] **Step 3: Commit**

```bash
git add backend/bench_diarization.py
git commit -m "feat(bench): A/B 对比脚本 v1 vs v2 diarization"
```

---

## Task 6: 端到端验证与代码检查

**Files:**
- Modify: （无，只运行检查）

- [ ] **Step 1: 运行全部新增/相关测试**

```bash
cd backend && uv run pytest tests/test_speaker_change_detector.py tests/test_funasr_stream_v2.py -v
```

Expected: 10 PASS, 0 FAIL

- [ ] **Step 2: 运行 ruff 检查**

```bash
cd backend && uv run ruff check src/diarization/speaker_change_detector.py src/stt/funasr_stream_v2.py tests/test_speaker_change_detector.py tests/test_funasr_stream_v2.py bench_diarization.py
```

Expected: 无错误

- [ ] **Step 3: 运行既有 STT 测试确保无回归**

```bash
cd backend && uv run pytest tests/test_stt_streaming.py tests/test_voiceprint_streaming.py -v
```

Expected: 既有测试全部 PASS

- [ ] **Step 4: 最终 Commit（如有格式修复）**

```bash
git add -A
git commit -m "chore: ruff 格式化与测试通过"
```

---

## Self-Review 清单

**1. Spec coverage**

| Spec 需求 | 对应 Task |
|---|---|
| 三阶段 SCD 算法（Phase1 lawyer-only → Phase2 seeding → Phase3 dual） | Task 2 + Task 3 |
| VoiceprintState 管理（lawyer/client/EMA） | Task 1 + Task 3 |
| 能量检测跳过 <0.001 窗口 | Task 3 (`test_skip_low_energy_window`) |
| 最小检测段长 2s（调用方过滤） | Task 4 (`_scd_split` duration<2000) |
| 最小拆分碎片 500ms | Task 4 (`_scd_split` >=500 判断) |
| 邻近切换点（<window_ms）合并去重 | Task 3 (`test_merge_nearby_changes`) + Task 2 代码 |
| funasr_stream_v2 独立文件、同接口、从 v1 import | Task 4 |
| `_scd_split` 插入 merge 后 ASR 前 | Task 4 (`_emit_stable_or_final_v2`) |
| bench_diarization 时间轴并排 + 粘连检测 + 汇总 | Task 5 |
| v1/v2 顺序跑、共用模型 | Task 5 (`_run_pipeline` 顺序调用) |
| A/B 阶段不修改 matcher/Enrollment | 全计划零改动现有文件 ✓ |

**2. Placeholder scan**

- 无 "TBD", "TODO", "implement later", "fill in details"
- 无 "Add appropriate error handling" 等模糊描述
- 每个代码步骤含完整代码块
- 无 "Similar to Task N"

**3. Type consistency**

- `detect_speaker_changes` 返回 `list[int]`（毫秒切分点），Task 2 与 Task 3 一致
- `VoiceprintState` 字段 `lawyer: np.ndarray`, `client: np.ndarray | None` 全计划一致
- `ClosedBy` 已扩展 `"scd"`（在 `utterance.py` 中已有，spec 确认）
- `_scd_split` 参数 `(bounds, snapshot, enrollment, voiceprint)` 全计划一致

---

## Execution Handoff

Plan complete and saved to `backend/docs/superpowers/plans/2026-05-30-speaker-change-detection.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
