# Cycle 6 设计:同步声纹标签(Naive 版)

**日期:** 2026-05-28
**Sprint:** 2(声纹)
**状态:** Brainstorm 完成,待 implementation plan

---

## 目标

让 `stream_stt` 产出的每一段 utterance 自带 `speaker` 标签(`lawyer` / `client` / `uncertain`),前端拿到 `transcript.final` 事件即可判断这一句是谁说的。

> 用户原话:"声纹介入最重要的是给说话的人打上标签,这样我就知道是谁说的话了。要不然我没有办法判断谁是谁。"

跨说话人粘连(handoff 已知问题 #1)的物理切分**不在本 cycle 范围**——这种 utt 整段会自然落进 `uncertain`,交给下游 AI 进一步分析。

---

## 范围

**做:**
1. utterance 关闭 → 串行跑 cam++ embedding(对整段 utt 音频)→ 跟律师注册 embedding 算余弦相似度 → 三态判定 → 设 `speaker` → yield
2. 阈值默认 τ_high=0.5 / τ_low=0.3,失败由测试反推校准
3. WS 会话开始时一次性加载律师 enrollment(硬编码 fixture 路径)

**不做(明确划清):**
- ❌ speaker 变化处强切 utterance 边界
- ❌ embedding 固定窗口 / 投机预跑 / 并行 ASR(优化项,Windows 实测后再决定)
- ❌ τ 自校准
- ❌ 前端上传 enrollment / 多客户声纹

---

## 跟现状的关系

| 模块 | 现状 | 本 cycle 改动 |
|---|---|---|
| `diarization/voiceprint.py` | Cycle 5 完成,`extract_embedding` 可用 | 无改动 |
| `diarization/enrollment.py` | `Enrollment(embedding, τ_high=0.5, τ_low=0.5)` | 默认改 `τ_high=0.5, τ_low=0.3`(双阈值真区分) |
| `diarization/matcher.py` | 二态(lawyer / client),单阈值 | 三态;新增 `uncertain` 分支 |
| `stt/funasr_stream.py::stream_stt` | `stream_stt(audio_chunks)`,speaker 永远 None | 签名加 `enrollment: Enrollment \| None = None`;非 None 时 yield 前打标 |
| `main.py` | session 不传 enrollment,speaker 全 None | session 开始加载 fixture enrollment,传入 stream_stt |

声纹**不参与切分**——funasr_stream 的 VAD / soft_cap / micropause 逻辑零改动。

---

## 改动点详细

### 1. `diarization/matcher.py`(改写)

```python
def match_speaker(audio, sr, enrollment) -> SpeakerLabel:
    emb = extract_embedding(audio, sr)
    s = float(np.dot(emb, enrollment.embedding))
    if s >= enrollment.tau_high:
        return "lawyer"
    if s <= enrollment.tau_low:
        return "client"
    return "uncertain"
```

接受 `Enrollment` 上的两个阈值,**不再硬编码 0.5**。

### 2. `diarization/enrollment.py`

```python
@dataclass
class Enrollment:
    embedding: np.ndarray
    tau_high: float = 0.5
    tau_low: float = 0.3
```

`enroll_speaker(audio, sr)` 签名不变,默认 τ 改成双值。

### 3. `stt/funasr_stream.py::stream_stt`

签名:
```python
async def stream_stt(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
    enrollment: Enrollment | None = None,
) -> AsyncIterator[Utterance]:
```

`_emit_stable_or_final` 内部:ASR text 拿到、确认非空、即将构造 Utterance 之前,如果 `enrollment is not None`:
```python
speaker = await asyncio.to_thread(
    match_speaker, seg_audio, SR, enrollment
)
```
然后 `Utterance(..., speaker=speaker)` 替代当前的 `speaker=None`。

`enrollment=None` 时行为完全不变(Sprint 1 测试不受影响)。

### 4. `main.py`

WS handler 顶端:
```python
from diarization.enrollment import enroll_speaker
import soundfile as sf

ENROLLMENT_WAV = Path(__file__).parent / "tests" / "fixtures" / "律师声纹注册.wav"

# 模块级单例,避免每个 session 重复加载
_lawyer_enrollment = None
def _get_enrollment():
    global _lawyer_enrollment
    if _lawyer_enrollment is None:
        audio, sr = sf.read(str(ENROLLMENT_WAV), dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        _lawyer_enrollment = enroll_speaker(audio, sr)
    return _lawyer_enrollment
```

`stream_stt(audio_iter(), enrollment=_get_enrollment())`。

---

## 测试

| 测试 | 性质 | 验收条件 |
|---|---|---|
| `test_enrollment_stable` (Cycle 5 已通过) | 无改动 | 继续通过 |
| `test_match_speaker_self_is_lawyer` (6a) | 现有,断言 "lawyer" 仍成立 | 继续通过 |
| **新增** `test_match_speaker_three_states` | 单元测试 | 构造 high / mid / low 余弦三种 enrollment 桩,断言对应 label |
| `test_streaming_match_accuracy` (现有,需小改) | 集成,声纹 + STT | clean utt 准确率 ≥ 95%,uncertain ≤ 30% |
| `test_full_wav_realtime_cer` (Sprint 1) | 回归 | LCS_ratio ≥ 0.85 不变,**记录 enrollment 启用后的新延迟** |

**`test_streaming_match_accuracy` 改动点:**目前测试在 `stream_stt` 外面单独调 `match_speaker(seg, SR, enrollment)`。本 cycle 后 utt 出来已经带 speaker,测试改成直接读 `utt.speaker`——这样验证的就是 `stream_stt` 内部那条声纹路径,而不是测试另起的旁路。

如果 `test_streaming_match_accuracy` 准确率不达 95%,**第一反应是调 τ_high / τ_low,不是改算法**。

---

## 已知会回归的指标

延迟会增加。Naive 同步实现下,P50 从 ~900ms → 预计 ~1500-1700ms。**接受此回归,作为 Windows 实测前的基线**。

slow 测试的 metrics.json 里会记录新延迟,作为后续优化的对照组。

---

## 不做的优化(显式留作 backlog)

| 优化 | 单项收益 | 暂不做的理由 |
|---|---|---|
| 固定 1-2s 窗口 embedding | 长 utt 从 ~750ms → ~100ms | 等 Windows 实测,可能机器够快用不上 |
| cam++ 与 ASR 并行 | 串行 → max | 实现简单但要先看 cam++ 真实速度 |
| VAD 阶段投机预跑 | 接近零延迟 | 工程量大,放 Cycle 7+ |
| 短 utt 跳过 embedding | 边界 case | 等首次测试看跳过率是不是个问题 |

---

## 验收清单

- [ ] `test_streaming_match_accuracy` 通过(accuracy ≥ 95%,uncertain ≤ 30%)
- [ ] `test_full_wav_realtime_cer` LCS_ratio 不回归
- [ ] 新延迟数据落进 metrics.json,作为优化前基线
- [ ] commit 完打 tag `backend-cycle-6`

---

## 风险

1. **τ 默认值不准**:cam++ 文献给的是参考值。fallback:测试失败时反推
2. **cam++ 在长 utt 上慢**:Naive 实现接受这点;Windows 实测后再优化
3. **enrollment 路径硬编码**:Sprint 3 加 WS 协议时再改;期间不能换律师

---

## 跟 spec `2026-05-27-realtime-copilot-architecture.md` 的对齐

| Q | spec 决策 | 本 cycle 状态 |
|---|---|---|
| Q3 三态 speaker | null/lawyer/client/uncertain | ✅ null 是异步路线的初始态,本 cycle 走同步 → 永远是终态三种之一 |
| Q5 全局单例声纹 | 注册一次,全局共用 | ✅ `_lawyer_enrollment` 模块级单例 |
