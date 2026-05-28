# Cycle 6 Voiceprint Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `stream_stt` 产出的每个 utterance 自带 `speaker` 标签(`lawyer` / `client` / `uncertain`),实现方式为同步串行 cam++ embedding(不优化)。

**Architecture:** matcher 改三态(双阈值);`stream_stt` 新增可选 `enrollment` 参数,utterance 关闭后 ASR 串行跑 cam++ 打标再 yield;`main.py` 模块级单例加载律师 enrollment fixture。声纹**不**参与切分,跨说话人 utterance 余弦相似度天然落在中间区 → `uncertain`,交下游 AI 兜底。

**Tech Stack:** Python 3.12 / FunASR(cam++) / asyncio / pytest / pytest-asyncio

**Spec:** [docs/superpowers/specs/2026-05-28-cycle6-voiceprint-labeling-design.md](../specs/2026-05-28-cycle6-voiceprint-labeling-design.md)

---

## File Structure

**Modify:**
- `backend/src/diarization/matcher.py` — 二态改三态(双阈值)
- `backend/src/diarization/enrollment.py` — `tau_low` 默认 0.5 → 0.3
- `backend/src/stt/funasr_stream.py` — `stream_stt` 加 `enrollment` 参数,`_emit_stable_or_final` 内同步打标
- `backend/main.py` — 模块级单例加载律师 enrollment,传入 `stream_stt`
- `backend/tests/test_voiceprint_streaming.py` — 新增三态单测;`test_streaming_match_accuracy` 改成直接读 `utt.speaker`

**No new files.** 所有改动落在现有模块里。

---

### Task 1: matcher 改三态

**Files:**
- Modify: `backend/src/diarization/matcher.py`
- Test: `backend/tests/test_voiceprint_streaming.py`

- [ ] **Step 1: Write the failing test**

在 `backend/tests/test_voiceprint_streaming.py` 末尾新增:

```python
def test_match_speaker_three_states(monkeypatch):
    """Cycle 6: matcher 三态分支按双阈值正确切换。

    用 monkeypatch 让 extract_embedding 返回受控向量,
    cos sim 落在三个区间分别期望 lawyer / uncertain / client。
    """
    from diarization import matcher

    # enrollment 用 [1, 0, 0],τ_high=0.6,τ_low=0.3
    e_lawyer = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    enrollment = Enrollment(embedding=e_lawyer, tau_high=0.6, tau_low=0.3)

    def fake_embed_factory(target_dot: float):
        # 返回跟 e_lawyer 内积 = target_dot 的单位向量
        v = np.array([target_dot, float(np.sqrt(1 - target_dot ** 2)), 0.0], dtype=np.float32)
        return lambda audio, sr: v

    dummy_audio = np.zeros(16000, dtype=np.float32)

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.8))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "lawyer"

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.45))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "uncertain"

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.1))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "client"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_voiceprint_streaming.py::test_match_speaker_three_states -v
```

Expected: FAIL,中间区间会被当前二态实现误判为 `client`(因为 `0.45 < 0.5 = tau_high`)。

- [ ] **Step 3: Rewrite matcher.py with three branches**

替换 `backend/src/diarization/matcher.py` 内容:

```python
"""speaker 三态分类:lawyer / client / uncertain。

cos sim ≥ τ_high → lawyer
cos sim ≤ τ_low  → client
其它              → uncertain(典型情形:跨说话人 utt,embedding 落在两人之间)
"""
from __future__ import annotations

from typing import Literal

import numpy as np

from diarization.enrollment import Enrollment
from diarization.voiceprint import extract_embedding

SpeakerLabel = Literal["lawyer", "client", "uncertain"]


def match_speaker(
    audio: np.ndarray,
    sr: int,
    enrollment: Enrollment,
) -> SpeakerLabel:
    """对单段音频判 speaker(三态)。"""
    emb = extract_embedding(audio, sr)
    s = float(np.dot(emb, enrollment.embedding))
    if s >= enrollment.tau_high:
        return "lawyer"
    if s <= enrollment.tau_low:
        return "client"
    return "uncertain"
```

- [ ] **Step 4: Run new test + existing matcher test**

```bash
cd backend && uv run pytest tests/test_voiceprint_streaming.py::test_match_speaker_three_states tests/test_voiceprint_streaming.py::test_match_speaker_self_is_lawyer -v
```

Expected: 两个都 PASS。`test_match_speaker_self_is_lawyer` 因为自匹配 cos sim ≈ 1.0 ≥ τ_high,继续返回 `"lawyer"`。

- [ ] **Step 5: Commit**

```bash
git add backend/src/diarization/matcher.py backend/tests/test_voiceprint_streaming.py
git commit -m "feat(diarization): matcher 改三态(lawyer/client/uncertain)"
```

---

### Task 2: Enrollment 默认阈值改双值

**Files:**
- Modify: `backend/src/diarization/enrollment.py`

- [ ] **Step 1: 改默认 τ_low**

替换 `backend/src/diarization/enrollment.py` 内容:

```python
"""声纹注册:输入律师注册音频,产出 Enrollment(embedding + 双阈值)。

τ_high / τ_low 用 cam++ 文献参考值起步;不达准确率时由 test_streaming_match_accuracy
反推校准。τ_high - τ_low 之间是 uncertain 中间带,跨说话人 utt 大概率落进这里。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from diarization.voiceprint import extract_embedding


@dataclass
class Enrollment:
    embedding: np.ndarray  # L2 归一化的 1D float32
    tau_high: float = 0.5
    tau_low: float = 0.3


def enroll_speaker(audio: np.ndarray, sr: int) -> Enrollment:
    """从注册音频产出 Enrollment。"""
    emb = extract_embedding(audio, sr)
    return Enrollment(embedding=emb)
```

- [ ] **Step 2: 跑所有声纹测试**

```bash
cd backend && uv run pytest tests/test_voiceprint_streaming.py -m "not slow" -v
```

Expected: 全 PASS(三态 + enrollment_stable + self_is_lawyer)。

- [ ] **Step 3: Commit**

```bash
git add backend/src/diarization/enrollment.py
git commit -m "feat(diarization): Enrollment 默认 τ_low 0.3 启用双阈值"
```

---

### Task 3: stream_stt 接受 enrollment 参数,utterance 同步打标

**Files:**
- Modify: `backend/src/stt/funasr_stream.py`
- Modify: `backend/tests/test_voiceprint_streaming.py` (改 `test_streaming_match_accuracy`)

- [ ] **Step 1: 改集成测试,改成直接读 `utt.speaker`**

打开 `backend/tests/test_voiceprint_streaming.py`,找到 `test_streaming_match_accuracy` 函数。把:

```python
        audio_stream = stream_wav_realtime(MAIN_WAV, chunk_ms=100, speed=1.0)
        labeled: list[tuple[object, str, str | None]] = []  # (utt, predicted, truth)
        async for utt in stream_stt(audio_stream):
            seg = main_audio[int(utt.t_start * SR) : int(utt.t_end * SR)]
            predicted = match_speaker(seg, SR, enrollment)
            truth = _attribute_speaker(utt.text, script_lines)
            labeled.append((utt, predicted, truth))
            logger.event("speaker.match", {
                "utt_id": utt.id,
                "t_start": utt.t_start,
                "t_end": utt.t_end,
                "text_preview": utt.text[:40],
                "predicted": predicted,
                "truth": truth,
            })
```

替换为:

```python
        audio_stream = stream_wav_realtime(MAIN_WAV, chunk_ms=100, speed=1.0)
        labeled: list[tuple[object, str, str | None]] = []  # (utt, predicted, truth)
        async for utt in stream_stt(audio_stream, enrollment=enrollment):
            predicted = utt.speaker  # 由 stream_stt 内部同步打标
            assert predicted is not None, (
                f"enrollment 已传入 stream_stt,speaker 不应为 None: utt={utt}"
            )
            truth = _attribute_speaker(utt.text, script_lines)
            labeled.append((utt, predicted, truth))
            logger.event("speaker.match", {
                "utt_id": utt.id,
                "t_start": utt.t_start,
                "t_end": utt.t_end,
                "text_preview": utt.text[:40],
                "predicted": predicted,
                "truth": truth,
            })
```

**同时删除测试中已经无用的 `main_audio` 加载**(找到这几行删掉):

```python
    main_audio, main_sr = sf.read(str(MAIN_WAV), dtype="float32", always_2d=False)
    if main_audio.ndim == 2:
        main_audio = main_audio.mean(axis=1)
    assert main_sr == SR, f"main WAV 应是 {SR}Hz, 实际 {main_sr}"
```

(原来用 `main_audio` 切 utt 段送 matcher,现在 utt 自带 speaker 就不需要了。`match_speaker` 的 import 保留,`test_match_speaker_self_is_lawyer` 还在用。)

这一步只改测试。运行测试现在会因 `stream_stt` 不接受 `enrollment` 参数而失败 —— 这就是 red。

- [ ] **Step 2: 验证测试现在会失败(red)**

```bash
cd backend && uv run pytest tests/test_voiceprint_streaming.py::test_streaming_match_accuracy -m slow -v --collect-only
```

(用 collect-only 避免真跑 8 分钟)Expected: collection PASS,但若真跑会因 `TypeError: stream_stt() got an unexpected keyword argument 'enrollment'` 立即失败。如果想确认,可以删 `-m slow` 不去掉 `@pytest.mark.slow` 直接 run —— pytest 会跳过 slow,但同文件其它测试会一起跑;collect 步骤已经够。

- [ ] **Step 3: 改 funasr_stream.py 加 enrollment 参数 + 同步打标**

打开 `backend/src/stt/funasr_stream.py`。

**(3a)** 在 import 区加(`from models.utterance import ClosedBy, Utterance` 之后):

```python
from diarization.enrollment import Enrollment
from diarization.matcher import match_speaker
```

**(3b)** 改 `stream_stt` 函数签名(第 210-212 行):

把:
```python
async def stream_stt(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
) -> AsyncIterator[Utterance]:
```

改成:
```python
async def stream_stt(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
    enrollment: Enrollment | None = None,
) -> AsyncIterator[Utterance]:
```

**(3c)** 在 `_emit_stable_or_final` 内部,找到现有的:
```python
            if not text:
                continue
            t_start = (t0 or 0.0) + s_ms / 1000.0
            t_end = (t0 or 0.0) + e_ms / 1000.0
            yield Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                closed_by=closed_by,
            )
```

替换为:
```python
            if not text:
                continue
            t_start = (t0 or 0.0) + s_ms / 1000.0
            t_end = (t0 or 0.0) + e_ms / 1000.0
            speaker = None
            if enrollment is not None:
                speaker = await asyncio.to_thread(
                    match_speaker, seg_audio, SR, enrollment
                )
            yield Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                speaker=speaker,
                closed_by=closed_by,
            )
```

注意 `seg_audio` 已在该作用域里定义(VAD 段切出来给 ASR 用的那段),直接复用。

- [ ] **Step 4: 跑回归测试确认 Sprint 1 行为不变**

```bash
cd backend && uv run pytest tests/test_stt_streaming.py -m "not slow" -v
```

Expected: 4 个 PASS(`stream_stt` 不传 enrollment 时 `speaker=None`,行为跟之前一样)。

- [ ] **Step 5: Commit**

```bash
git add backend/src/stt/funasr_stream.py backend/tests/test_voiceprint_streaming.py
git commit -m "feat(stt): stream_stt 加 enrollment 参数,utterance 同步打 speaker 标签"
```

---

### Task 4: main.py 接入律师 enrollment

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 改 main.py 加载 enrollment 单例 + 传入 stream_stt**

替换 `backend/main.py` 全文:

```python
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent / "src"))
from diarization.enrollment import Enrollment, enroll_speaker  # noqa: E402
from stt.funasr_stream import stream_stt  # noqa: E402

ENROLLMENT_WAV = Path(__file__).parent / "tests" / "fixtures" / "律师声纹注册.wav"

app = FastAPI()

_lawyer_enrollment: Enrollment | None = None


def _get_lawyer_enrollment() -> Enrollment:
    """模块级单例:律师 enrollment 全进程加载一次。

    Sprint 3 会把这换成 WS 协议里前端上传 / 用户绑定的 enrollment。
    """
    global _lawyer_enrollment
    if _lawyer_enrollment is None:
        audio, sr = sf.read(str(ENROLLMENT_WAV), dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        _lawyer_enrollment = enroll_speaker(audio, sr)
    return _lawyer_enrollment


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()

    enrollment = _get_lawyer_enrollment()
    audio_q: asyncio.Queue[tuple[np.ndarray, float] | None] = asyncio.Queue()
    t0 = time.monotonic()

    async def audio_iter():
        while True:
            item = await audio_q.get()
            if item is None:
                return
            yield item

    async def consume_stt():
        async for utt in stream_stt(audio_iter(), enrollment=enrollment):
            await ws.send_json({
                "type": "transcript",
                "id": utt.id,
                "text": utt.text,
                "t_start": utt.t_start,
                "t_end": utt.t_end,
                "speaker": utt.speaker,
                "closed_by": utt.closed_by,
                "is_final": True,
            })

    stt_task = asyncio.create_task(consume_stt())

    try:
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                break

            if "bytes" in data:
                audio = np.frombuffer(data["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                await audio_q.put((audio, time.monotonic() - t0))

            elif "text" in data:
                msg = json.loads(data["text"])
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                # intent confirm/dismiss 待 Sprint 3 Orchestrator 接入

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await audio_q.put(None)
        try:
            await stt_task
        except Exception:
            pass
```

- [ ] **Step 2: 冒烟验证 main.py 可加载**

```bash
cd backend && uv run python -c "from main import app, _get_lawyer_enrollment; e = _get_lawyer_enrollment(); print(f'enrollment loaded, embedding shape={e.embedding.shape}, tau_high={e.tau_high}, tau_low={e.tau_low}')"
```

Expected: `enrollment loaded, embedding shape=(192,), tau_high=0.5, tau_low=0.3`(具体维度看 cam++ 实际输出,常见 192;τ 必须是上面默认值)。

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(ws): session 启动加载律师 enrollment 单例并传入 stream_stt"
```

---

### Task 5: 跑完整集成测试 + 延迟回归基线 + 打 tag

**Files:**
- Run: `backend/tests/test_voiceprint_streaming.py::test_streaming_match_accuracy` (slow)
- Run: `backend/tests/test_stt_streaming.py::test_full_wav_realtime_cer` (slow)

- [ ] **Step 1: 跑声纹准确率集成测试**

```bash
cd backend && uv run pytest tests/test_voiceprint_streaming.py::test_streaming_match_accuracy -m slow -s -v
```

Expected: PASS。accuracy ≥ 0.95,uncertain_pct ≤ 0.30。

**如果 accuracy < 0.95:**
- 看 `tests/runs/<ts>_voiceprint_accuracy/metrics.json` 找原因
- 如果 uncertain 占比正常但分错很多,说明 τ_high 太低 → 拉到 0.55
- 如果 uncertain 占比过高(>30%),说明 τ_high 太高 → 降到 0.45,或 τ_low 升到 0.35
- 改 `backend/src/diarization/enrollment.py` 默认值,重跑

**如果 uncertain_pct > 0.30 但 accuracy ≥ 95%:**
- 收紧中间带,把 τ_high 降到 0.45 或 τ_low 升到 0.35
- 重跑

- [ ] **Step 2: 跑 Sprint 1 STT 回归测试,记录新延迟**

```bash
cd backend && uv run pytest tests/test_stt_streaming.py::test_full_wav_realtime_cer -m slow -s -v
```

Expected: PASS。LCS_ratio ≥ 0.85 不变。延迟会比 Sprint 1 慢(预计 P50 1500-1700ms),这是 naive 同步实现的预期回归。

- [ ] **Step 3: 计算新延迟基线**

```bash
cd backend && uv run python3 -c "
import json
from pathlib import Path
import sys

run_root = Path('tests/runs')
latest_full = sorted([p for p in run_root.iterdir() if p.name.endswith('_full_wav_cer')])[-1]
events = [json.loads(l) for l in (latest_full / 'events.jsonl').read_text().splitlines()]
finals = [e for e in events if e['kind'] == 'transcript.final']
lats = sorted([e['t_wall'] - e['t_end'] for e in finals])
print(f'{latest_full.name}: n={len(lats)} min={min(lats):.3f} P50={lats[len(lats)//2]:.3f} P95={lats[int(len(lats)*0.95)]:.3f} max={max(lats):.3f}')

latest_vp = sorted([p for p in run_root.iterdir() if p.name.endswith('_voiceprint_accuracy')])[-1]
vp_metrics = json.loads((latest_vp / 'metrics.json').read_text())
print(f'{latest_vp.name}: accuracy={vp_metrics[\"accuracy\"]} uncertain_pct={vp_metrics[\"uncertain_pct\"]} cross_speaker_pct={vp_metrics[\"cross_speaker_pct\"]}')
"
```

Expected: 输出延迟和准确率数字,用于 commit message。

- [ ] **Step 4: Commit 延迟基线说明 + tag backend-cycle-6**

```bash
git commit --allow-empty -m "$(cat <<'EOF'
chore(cycle-6): 同步声纹标签 naive 基线指标

延迟回归(对照 backend-gate-1):预期 P50 增加 ~500-800ms,
作为 Windows 实测前的 baseline。优化项(固定窗口 / 并行 ASR /
投机预跑)放 backlog,实测后再决定。
EOF
)"
git tag -a backend-cycle-6 -m "Cycle 6 完成:utterance 同步打 speaker 标签(三态)"
```

(如果之前某 step 已经把这些改动 commit 进去了,这一步可能不需要 empty commit,直接打 tag 即可。)

- [ ] **Step 5: 验证 tag**

```bash
git tag --list && git show backend-cycle-6 --no-patch --format="%h %s"
```

Expected: 看到 `backend-gate-1` 和 `backend-cycle-6` 两个 tag。

---

## Done Criteria

- [ ] `test_match_speaker_three_states` PASS
- [ ] `test_match_speaker_self_is_lawyer` PASS(回归)
- [ ] `test_enrollment_stable` PASS(回归)
- [ ] `test_streaming_match_accuracy` PASS,accuracy ≥ 0.95,uncertain ≤ 0.30
- [ ] `test_full_wav_realtime_cer` PASS,LCS_ratio ≥ 0.85
- [ ] Sprint 1 快测试 4 个全过
- [ ] tag `backend-cycle-6` 已打
- [ ] 新延迟基线数据记录在 commit message 或 metrics.json
