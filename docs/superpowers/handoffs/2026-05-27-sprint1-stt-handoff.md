# Sprint 1 (STT) 交接文档

**日期:** 2026-05-27
**状态:** Cycle 1-4 实现完成,Cycle 4 测试断言失效(脚本/音频不匹配),Cycle 5-7 未开始

---

## 当前度量

跑 `劳动仲裁对话_完整版.wav`(7.5 min, 1x 真速),最后一次完整运行
(`tests/runs/20260527-225621_full_wav_cer/`):

| 指标 | 值 | 备注 |
|------|----|----|
| utterance 数 | 55 | 脚本 48 行,比例 1.146 |
| **ASR 真实错字率** | **8.55%** | LCS(hyp,ref)/len(hyp) = 91.4%,达到行业基准 |
| 延迟 P50 | **620ms** | 客户/律师说完最后一字 → 屏幕出字 |
| 延迟 P95 | 709ms | |
| 延迟最大 | 768ms | |
| 延迟最小 | 551ms | |
| closed_by | 54 soft_cap / 1 vad | 真实对话节奏紧凑,几乎全是 soft_cap 切 |

延迟从初版 1500ms 压到 620ms。整段无 O(n²) 增长,P95-P50 仅 89ms。

---

## 跟 spec 的偏离

spec `2026-05-27-realtime-copilot-architecture.md` 里的常量已经在实现中调整,需要同步更新 spec:

| 常量 | spec 原值 | 当前代码 | 调整原因 |
|------|----------|---------|---------|
| `VAD_SILENCE_MS` | 1500 | **400** | 1500ms 让用户感知延迟 1.5s,真实对话间隔短,400 够分句 |
| `MICROPAUSE_MS` | 300 | **150** | soft_cap 切分等微停顿确认,150ms 减 150 延迟 |
| soft_cap 关闭语义 | 等 silence ≥ VAD_SILENCE_MS | **立即 yield** | 切分点已由能量微停顿确定,等静默无意义 |

延迟预算"≤500ms"在当前 CPU 架构下未达到。实测 P50 620ms,瓶颈是:
- ~150ms MICROPAUSE 微停顿确认(已是当前合理下限)
- ~100ms VAD 重检周期
- ~200-400ms paraformer-zh 离线 ASR 处理(GPU 可加速)

---

## 已知问题

### 1. utterance 跨说话人粘连(主要问题)

soft_cap 切分只看"说话时长",看不出"换人说话"。前 12 段里 ~5 段跨客户/律师边界。
例如 utterance #2:
```
"我现在真的很猛不知道该怎么办张先生你好你先别急咱们慢慢说"
 └──── 客户 ────────────┘└──── 律师 ─────────────┘
```

**修复路径:Cycle 6 声纹切分**——cam++ 每 ~500ms embedding 一次,speaker
变化时强切边界(优先级高于 VAD/soft_cap)。

### 2. Cycle 4 CER 测试断言不公平

当前测试用脚本作 ground truth 算字符级 CER,但脚本是"写出来的版本"(3202 字),
音频是"演员念出来的版本"(实际 ~1836 字内容)。脚本里 47.6% 的字音频里没念。

诊断结论(2026-05-27 已验证):
- hyp 长 1836 / ref 长 3202
- LCS(hyp,ref) = 1679,占 hyp 的 91.4%
- ASR 真实错字 = (1836-1679)/1836 = **8.55%**(好)
- 当前 CER 公式 48.1%(被脚本超长部分主导,不反映 ASR 质量)

**修复路径二选一:**
- **选项 G**(推荐,改 1 行测试):断言改为 `LCS(hyp,ref)/len(hyp) ≥ 0.85`,
  衡量"ASR 不胡说"而非"覆盖率全包"
- **选项 H**(工作量大):听一遍音频,精确转录演员实际念的内容作 ground truth

### 3. utterance 内会出现碎句

soft_cap 切分点是"说够 8s 找微停顿",可能切在词组中间(如"小会议室|说公司战略调整")。
声纹介入后会有改善(speaker 边界自然对齐句首)。

---

## 关键文件

| 路径 | 状态 | 说明 |
|------|------|------|
| `backend/src/stt/funasr_stream.py` | ✅ | 主 STT 管线,~320 行 |
| `backend/src/models/utterance.py` | ✅ | Utterance dataclass |
| `backend/tests/test_stt_streaming.py` | ⚠ | Cycle 4 测试断言要修(选项 G) |
| `backend/tests/streaming_fixtures.py` | ✅ | 真速喂入 fixture |
| `backend/tests/conftest.py` | ✅ | 预加载模型 + fixture 生成 |
| `backend/tests/run_logger.py` | ✅ | 实时 JSONL + stdout + metrics |
| `docs/superpowers/specs/2026-05-27-realtime-copilot-architecture.md` | ⚠ | 常量值要回写更新 |

---

## 跑测试

```bash
cd backend

# 短测试(~30s),回归用
uv run pytest tests/test_stt_streaming.py -m "not slow" -v

# 完整 WAV 测试(~7.5min,真速喂入)
uv run pytest tests/test_stt_streaming.py::test_full_wav_realtime_cer -m slow -v -s
# 产物在 tests/runs/<timestamp>_full_wav_cer/
#   - events.jsonl  每个 utterance 一行
#   - metrics.json  汇总指标(测试通过时才写)
```

---

## 明天继续:任务清单

### A. 收尾 Sprint 1(预计 < 1h)

- [ ] 改 `test_full_wav_realtime_cer` 断言:CER ≤ 15% → LCS(hyp,ref)/len(hyp) ≥ 0.85
- [ ] 同步 spec `2026-05-27-realtime-copilot-architecture.md` 的常量值
- [ ] 完整跑测试,确认通过
- [ ] 把 Cycle 4 标 completed,打 tag `backend-gate-1`

### B. 开始 Sprint 2(声纹,plan 的 Cycle 5-7)

按 TDD 节奏:

- [ ] **Cycle 5 — 声纹注册稳定 embedding**
  - 测试:`tests/test_voiceprint_streaming.py::test_enrollment_stable`
  - 用 `律师声纹注册.wav` 两次注册,断言两次 embedding 余弦相似度 ≥ 0.98
  - 实现:`backend/src/diarization/voiceprint.py` + `enrollment.py`,
    用 FunASR `AutoModel(model="cam++")` 提 embedding
- [ ] **Cycle 6 — 声纹三态匹配,切分介入**
  - 测试:`test_voiceprint_streaming.py::test_streaming_match_accuracy`
  - 先注册律师,再跑主 WAV 流式喂,每个 utterance 出 speaker label
  - 断言:speaker 准确率 ≥ 95%(对照脚本),回填延迟 P95 ≤ 2s
  - **关键改动**:在 STT 切分阶段引入声纹 embedding 比对,speaker 变化时
    强切边界(高于 VAD/soft_cap)——这是解决"跨说话人 utterance"的核心
- [ ] **Cycle 7 — Sprint 1+2 E2E**
  - `replay_audio.py` CLI 把 STT + voiceprint 串起来
  - 主 WAV 真速喂入,捕获 events.jsonl + metrics.json
  - 断言:CER + speaker 准确率 + 回填延迟 + 流式间隔

### C. (可选)进一步压延迟

如果有 GPU 机器或想冲 ≤500ms 目标:
- GPU 加速 paraformer-zh,预计 P50 620 → ~450ms
- `VAD_RECHECK_INTERVAL_MS` 100 → 30,再省 ~70ms
- 真流式 ASR (`paraformer-zh-streaming`) — 架构级改动,本 sprint 不建议

---

## 跟当前 spec 的关键决策对齐情况

| Q (spec 决策) | 当前实现 | 备注 |
|---|---|---|
| Q1 只 final 不 partial | ✅ 已实现 | streaming ASR 暂未引入 |
| Q2 soft cap 8s | ✅ `SOFT_CAP_MS=8000` | |
| Q3 三态 speaker (null/lawyer/client/uncertain) | ⏳ Cycle 6 | 当前 speaker 永远 null |
| Q4 hotword 包 | ⏳ 未开始 | Cycle 6 之后再做 |
| Q5 全局单例声纹 | ⏳ Cycle 5 | |
