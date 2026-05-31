# UI 打磨：洞察渲染、引用、滚动条、时间戳、画像倒序与快答前缀

## 概述

对实时会谈页的 7 项 UI/UX 打磨，涉及前端渲染、后端数据模型扩展、prompt 微调。

## 1. 洞察 Markdown 渲染

**现状：** `InsightCard` 和 `SuggestionCard.ReadyCard` 用 `<p>` 纯文本显示 AI 输出，`**加粗**`、`- 列表` 等 markdown 语法不渲染。

**改动：**
- `InsightCard` 的 `{insight.text}` 和 `ReadyCard` 的 `{suggestion.text}` 改用 `react-markdown` + `remark-gfm` 渲染
- 使用已有的 `react-markdown`（10.1.0）和 `remark-gfm`（4.0.1），无需新依赖
- 限制允许的元素集合：`p, strong, em, code, ul, ol, li, blockquote, a, br, pre`（禁用 heading/img/table 等对行内洞察不必要的元素）
- 通过 `components` prop 重写样式，确保渲染输出与现有设计系统一致

## 2. 洞察添加 utt_id 引用

**现状：** `Insight` 类型有 `uttId` 字段，但 `InsightCard` 不展示。

**改动：**
- `InsightCard` 在文本下方加一行灰色小字 `来源: {insight.uttId}`
- 样式：`text-[10px] text-ink-muted font-mono`

## 3. 滚动条统一细条样式

**现状：**
- `InsightStream` 用 `ScrollArea` 组件（via base-ui），thumb 宽 10px，颜色 `bg-border`
- `TranscriptPanel` 和 `ProfilePanel` 用原生 `overflow-auto`（系统默认滚动条，macOS 下尚可，Windows 下很突兀）

**改动：**
- `TranscriptPanel` 和 `ProfilePanel` 改用 `ScrollArea` 组件
- `scroll-area.tsx` 中 scrollbar 宽度从 `data-vertical:w-2.5`（10px）改为 `data-vertical:w-1.5`（6px）
- thumb 颜色从 `bg-border` 改为 `bg-border/50`，hover 时 `bg-border/80`

## 4. 转写添加时间戳

**现状：** `TranscriptLine` 有 `timestamp` 字段，`TranscriptPanel` 每行只显示 speaker 标签 + 文本。

**改动：**
- 每行前加相对时间戳（距录音开始的 `MM:SS`）
- 格式：`{minutes}:{seconds.toString().padStart(2, '0')}`
- 样式：`text-[10px] text-ink-muted font-mono w-10 shrink-0`
- 布局调整：当前 `flex gap-2` 改为三列 `[时间] [角色] [文本]`

## 5. 画像显示时间戳和 utt_id 引用

**后端改动：**

`ProfileEntryPayload`（events.py）加字段：
```python
class ProfileEntryPayload(BaseModel):
    key: str
    value: str
    subject: str
    timestamp: float  # 新增：录入时间（相对音频秒数）
    source_utt_id: str  # 新增：触发此条目的 utterance id
```

`orchestrator.py` 的 `handle_utterance` 中 emit `ProfileUpdated` 时传 `timestamp=e.timestamp` 和 `source_utt_id=e.source_utt_id`。

HTTP history 端点 `/api/sessions/{session_id}/history` 的 `profile_entries` 返回加 `timestamp` 和 `source_utt_id` 字段。

**前端改动：**

`ProfileEntryItem` 类型加：
```ts
timestamp?: number
sourceUttId?: string
```

`ProfilePanel` 每个条目下方显示：
- 时间（格式化为相对时间 `MM:SS`）
- `来源: {sourceUttId}`

## 6. 去掉"快答"标题前缀

**现状：** AI 有时会在直接洞察输出中自发加上 `**快答**：` 前缀。

**改动：**
- `prompts.py` 的 `get_child_system_prompt()` 中加一句：`不要在你的快答回复中加"快答"标题或任何前缀，直接说出对律师有用的内容即可。`
- 前端 `InsightCard` 渲染时做兜底 strip：用正则去掉开头的 `**快答**：` 或 `**快答**:` 或 `快答：`

## 7. 画像倒序排列

**现状：** `ProfilePanel` 中 entries 按录入顺序渲染，最新在最后。

**改动：**
- `categoryEntries()` 返回 `profile.entries.filter(...).reverse()`
- 所有使用 `categoryEntries` 的渲染区域自动受益（基本信息、情绪状态、关键主张、风险暴露、已确认事实）

## 验证标准

- [ ] 洞察卡片中 markdown 语法正确渲染（加粗、列表可见）
- [ ] 洞察卡片底部显示 `来源: xxx` utt_id 引用
- [ ] 三个面板（洞察、转写、画像）滚动条样式一致，6px 细条
- [ ] 转写面板每行前有时间戳 `MM:SS`
- [ ] 画像条目显示时间戳和 utt_id 引用
- [ ] 画像条目按倒序排列（最新在上）
- [ ] AI 输出不再出现 `**快答**：` 前缀（prompt 修改 + 前端兜底 strip）
- [ ] 后端 test_events_schema.py 通过（ProfileEntryPayload 加字段后的 round-trip）
- [ ] 前端 tsc 通过，现有测试不退化
