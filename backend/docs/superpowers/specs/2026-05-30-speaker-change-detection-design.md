# Speaker Change Detection — 解决跨说话人对话粘连

## 问题

`merge_with_close_reason` Phase 1 用静音长度（VAD_SILENCE_MS=400ms）判断是否合并相邻 VAD 段。
律师→客户切换时停顿可能 < 400ms → 被错误合并 → 一个 utterance 里混进两个人的话。

**根因**：管线只有"音量"这一个分割信号，没有"声纹"信号。同人停顿和跨人切换的静音长度有重叠区，单靠静音永远区分不开。

## 方向

**B2：声纹驱动的段内 Speaker Change Detection。** VAD 合并后，对长段滑窗扫描 cam++ embedding，在相邻窗口声纹跳变处切开。

- 零延迟增加（SCD 每个长段多跑 2-8 次 cam++，每次 < 50ms，不引入新缓冲）
- 不引入新模型（复用现有 cam++ + enrollment.embedding）
- 两说话人 + 一已注册 = 不需要聚类，embedding 比对即可

## 架构

三个新文件，不动任何现有文件：

```
backend/src/diarization/speaker_change_detector.py   ← SCD 模块（纯函数 + 声纹状态）
backend/src/stt/funasr_stream_v2.py                  ← 新 STT 管线（独立实现，同 v1 接口）
backend/bench_diarization.py                         ← A/B 对比脚本
```

### B2 管线数据流

```
音频 chunks → 累积 buffer → fsmn-vad（不变）
  → raw segments [(s_ms, e_ms), ...]
  → merge_with_close_reason（不变，Phase 1 静音合并）
  → 【新增】_scd_split(bounds, snapshot, enrollment):
      对每个 > 2s 的 bound 跑 detect_speaker_changes()
      有切换点 → 拆成 sub-bounds（closed_by="scd"）
      过滤 < 500ms 碎片
  → 每个 sub-bound：投机 ASR + speaker match → yield utterance（不变）
```

## Speaker Change Detector

### 接口

```python
def detect_speaker_changes(
    seg_audio: np.ndarray,
    voiceprint: VoiceprintState,
    sr: int = 16000,
    window_ms: int = 1500,
    step_ms: int = 500,
    delta_threshold: float = 0.25,
    lawyer_threshold: float = 0.40,
    margin: float = 0.10,
) -> list[int]:
```

### 算法（三阶段，对应动态声纹生命周期）

**阶段 1 — 仅 lawyer 声纹（session 初始）**

每个窗口提 embedding(e)，与 lawyer 比对：
- s_l = cos(e, lawyer)
- s_l ≥ 0.40 → 律师窗口
- s_l < 0.40 → 非律师窗口
- 相邻窗口 s_l 跳变 > 0.25 且越过 0.40 线 → 标记切换点

**阶段 2 — 种子化 client 声纹**

检测到 s_l 从 > 0.50 骤降到 < 0.20（高置信度 lawyer→非lawyer 切换）：
- 取切换后第一个窗口的 embedding 作为 client 种子
- 进入阶段 3

**阶段 3 — 双声纹比对**

```python
# 每个窗口：
s_l = cos(e, voiceprint.lawyer)
s_c = cos(e, voiceprint.client)
diff = s_l - s_c     # >0 → lawyer, <0 → client

# 切换检测：
相邻窗口 diff 正负翻过 margin(±0.10) → 标记切换点

# client 声纹滚动更新（仅高置信度窗口）：
if diff < -0.30:
    voiceprint.client = EMA(voiceprint.client, e, weight=0.15)
```

### 为什么跟 lawyer 比，不跟相邻窗口互相比

lawyer 声纹是已知的绝对参考点。相邻窗口互相对比无法区分"同人延续"和"换人但两人声纹差异小"。"与 lawyer 比对"的语义清晰：sim 高 = lawyer，sim 低 = client（只有两个人）。

### 风险

| 风险 | 缓解 |
|---|---|
| cam++ 对 1.5s 短窗不稳定 | 窗口长度可调参，最小 1s |
| 静默窗口被当成 client | 能量检测跳过能量 < 0.001 的窗口 |
| false positive（同人被错切） | delta_threshold + lawyer_threshold 双重条件 + margin 控制 |
| false negative（没检测到切换） | 最坏退化成 v1，不比现在更差 |
| client 种子被脏段污染 | EMA 权重 0.15 保守更新，仅高置信度窗口参与 |

### 设计约束

- 最小检测段长：2s（2 个不重叠窗口，保证比较有效性）
- 最小拆分碎片：500ms（更短则 ASR + embedding 不可靠，直接丢弃）
- 已合并的邻近切换点（间距 < window_ms）再次合并去重

## funasr_stream_v2

### 与 v1 的关系

独立文件，相同外部接口。从 v1 import 共享工具函数：`_get_models`、`_utt_id`、`_vad_segments_ms`、`_asr_one`、`merge_with_close_reason` 等。

### 关键改动

`_emit_stable_or_final_v2` 和原版只有一处不同 —— 在 `merge_with_close_reason` 之后、逐段 ASR 之前，插入 SCD 拆分：

```python
# v1：
for (s_ms, e_ms, closed_by) in bounds:
    → 投机 ASR → speaker match → yield

# v2：
sub_bounds = _scd_split(bounds, snapshot, enrollment)
for (s_ms, e_ms, closed_by) in sub_bounds:
    → 投机 ASR → speaker match → yield  （完全不变）
```

### `_scd_split` 逻辑

```
对每个 bound (s_ms, e_ms, closed_by):
  if enrollment 不存在 或 duration < 2000ms:
    原样保留
  else:
    changes = detect_speaker_changes(seg_audio, voiceprint)
    if changes 为空: 原样保留
    else: 按 changes 切成 N 段
      - 每段 closed_by="scd"
      - 丢弃 < 500ms 的碎片
```

### VoiceprintState 管理

SCD 内部维护 `VoiceprintState`（包含 `lawyer`、`client` 及 EMA 权重）。与 `matcher.py` 的 `Enrollment.client_embedding` 在 A/B 阶段独立运作，后续可合并。

## A/B 对比脚本

### 运行方式

```
uv run python bench_diarization.py \
  --wav tests/fixtures/劳动仲裁对话_完整版.wav \
  --enrollment tests/fixtures/律师声纹注册.wav
```

### 执行流程

1. 加载 WAV → float32 16kHz mono
2. 加载律师 Enrollment（register）
3. WAV 切成帧（~100ms/帧，模拟 WebSocket 实时帧率）
4. 创建两份相同的 chunk 迭代器
5. 顺序喂给 `stream_stt`(v1) 和 `stream_stt_v2`(v2)
6. 收集两边所有 utterance
7. 对比输出报告

### 对比输出

**1. 时间轴并排表** — v1 speaker+text | v2 speaker+text，按时间对齐

**2. 粘连检测**（核心指标）：
```
对每个 v1 utterance (t_start, t_end, spk_v1):
  overlaps = v2 utterance 中时间重叠的集合
  1 个 overlap 且 speaker 一致 → 正常
  1 个 overlap 但 speaker 不同 → 标签不一致
  ≥2 个 overlap 且 speaker 不同 → ⚠️ 跨说话人粘连
  ≥2 个 overlap 且 speaker 相同 → 仅切分粒度不同
```

**3. 汇总统计**：
```
                     V1          V2
  Utterances:        12          15
  Lawyer:            7           7
  Client:            3           5
  Uncertain:         2           3
  Avg duration:      3.8s        3.0s
  SCD splits:        —           3
```

### 注意事项

- 时间戳对齐允许 ±200ms 容差
- enrollment 文件不存在时，两边都不做 speaker 匹配，对比纯切分差异
- v1 和 v2 顺序跑（共用 cam++ 模型实例，避免 GPU 内存竞争）

## 未涉及

- 不修改 `matcher.py` 的 `match_speaker` 或 `Enrollment.client_embedding`（A/B 阶段保持独立）
- 不替换 fsmn-vad（VAD 本身足够好，问题在合并阶段）
- 不引入新模型（cam++ 已在用）
