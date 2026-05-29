---
name: chronology-builder
description: >
  从文档来源构建法律时间线 — 提取带日期事件、去重、按案件理论标记重要性（🔴/🟡/⚪）。
  在建立时间线前要求案件已完成 intake。
  支持 matter 模式和 documents 模式。
---

# /chronology-builder

1. 加载 practice profile → 风险校准、案件理论偏好、特权规则。
2. 遵循下方工作流和参考。
3. **Gate 0 — Privilege：** 强制在提取前选择 cleared / mixed / abort。
4. 从案件档案和文档存储中提取带日期事件。
5. 去重、按案件理论标记重要性、逐条标注来源。
6. 生成：工作表（完整表格含标记）+ 事实陈述变体（🔴+相关🟡，叙述体）。
7. 写入 `matters/[slug]/chronology.md`。

---

# Chronology

## Purpose

把时间线变成可用的案件理论工具 — 不是事件清单，而是按重要性标记的、可审计的叙事基础。

## Load context

- `matters/[slug]/matter.md` — 案件理论、立场、关键日期
- `matters/[slug]/history.md` — 已记录事件
- `matters/_log.yaml` — 确认案件存在（conflicts gate 已通过）
- `practice profile` — 特权规则、工作产品标记规范

## Conflicts gate — unbypassable

构建时间线前，检查 `_log.yaml` 中的案件 slug。如果案件不在 `_log.yaml` 中，拒绝并路由：

> "我在案件日志中看不到 [案件 slug]。先运行 `/matter-intake` 让利益冲突检查运行并建立案件工作空间。我不会在未 intake 的案件上构建时间线 — 利益冲突检查是 gate。"

## Two modes

- **`--matter`（默认内部）**：从案件文件、文档存储、matter.md 理论中提取。
- **`--documents`（默认律所）**：从 eDiscovery 成果、带 Bates 编号集合中提取。

## Gate 0: Privilege filter — before extraction

在提取任何事件之前，强制选择：

> **Privilege posture.** 你要构建时间线的来源是否：
> - **Cleared** — 所有文档已 cleared for work-product / 特权（如对方生产、公开记录、内部非特权文件）
> - **Mixed** — 来源包含特权和非特权材料；你将在提取后审查并标记特权条目
> - **Abort** — 你不确定特权状态；先运行 privilege review

如果 **Abort** → 停止。建议运行 privilege review 或咨询 supervising attorney。

如果 **Mixed** → 继续，但每条时间线条目必须标注 `source_privilege: [cleared | privileged | mixed | unknown]`。
特权条目在共享前必须被剥离或单独标记。

## Extraction rules

### What counts as an event

- 任何有日期或可以合理锚定到日期的发生事项
- 包括：行为、通知、变更、发现、沟通、提交、裁决
- 不包括：法律结论、策略讨论、律师分析（这些是 work product，不是 chronology 条目）

### Date handling

- **精确日期**：优先使用 YYYY-MM-DD
- **月份**：YYYY-MM → 标注 `[month-only]`
- **年份**：YYYY → 标注 `[year-only]`
- **相对日期**："合同签订后两周" → 如可锚定则计算绝对日期；如不能则保留相对描述并标注 `[relative: anchor unknown]`
- **矛盾日期**：同一事件在不同来源中有不同日期 → 保留所有版本，标注 `[date conflict: source A says X, source B says Y]`

### De-duplication

- 同一事件在多个来源中出现 → 合并为一条，保留所有来源指针
- "同一事件"标准：相同日期（或合理接近）+ 相同核心行为 + 相同当事人
- 接近但不重复的事件保留为独立条目（如"3月1日发函"和"3月3日收悉回函"是两件事）

## Significance tagging — per case theory

每条事件按其对案件理论的重要性标记：

- **🔴 Critical**：直接支持或破坏案件理论；庭审开场陈述中会提到的事实；无此事实，理论不成立
- **🟡 Relevant**：与案件相关，支持背景或次要论点，但不直接决定结果
- **⚪ Context**：背景信息，帮助理解时间线，但不太可能在任何实质性文件中被引用

标记纪律：
- "Over-flagging is corrected by counsel in review (two-way door). Prefer the recoverable error."
- "A chronology of 300 entries with 300 🔴 tags has no tags."
- 标记基于 matter.md 中 capture 的案件理论。如果理论改变，标记应重新评估。
- 法律断言（如"违约"、"违法解除"）不在 chronology 中做结论；时间线记录"X 于 Y 日通知解除"，而不是"X 违法解除"。

## Source attribution

每条条目标注来源。绝不静默补充缺口：

```
【YYYY-MM-DD】🔴
事件：...
来源：劳动合同第3条（intake 提供）
```

来源标签选项：
- `[user provided]` — 用户/律师在 intake 或更新中提供
- `[document: filename]` — 具体文档
- `[model knowledge — verify]` — 模型知识，必须验证
- `[inference — verify]` — 推理得出，必须验证

## Output formats

### 1. Working chronology（默认）

完整表格，所有条目，含标记和来源。

```markdown
# Chronology: [案件名称]
**Built:** [date]
**Theory:** [来自 matter.md 的案件理论一句话]
**Privilege posture:** [cleared / mixed]
**Sources:** [列出所有来源文档]

---

| Date | Event | Tag | Source | Privilege |
|---|---|---|---|---|
| YYYY-MM-DD | ... | 🔴 | [source] | cleared |
| YYYY-MM-DD | ... | 🟡 | [source] | cleared |
| YYYY-MM | ... | ⚪ | [source] | privileged |
```

### 2. Statement-of-Facts variant

仅 🔴 + 相关 🟡，按时间顺序排列成叙述体，用于诉状、答辩状、仲裁申请书。

```markdown
# Statement of Facts: [案件名称]
**Derived from:** chronology.md built [date]
**Scope:** 🔴 critical + 🟡 relevant events only

[按时间顺序排列的叙述体。每个段落一个事件或紧密相关的事件组。
段落内可引用来源如"（见劳动合同第3条）"。
不包含法律结论或论证。]
```

### 3. Witness-specific filter

按证人筛选：仅显示该证人可能作证的事件，附准备提示。

## Discipline rules

- **Never resolves contradictions.** 记录矛盾，标注 `[conflict]`，让 counsel 决定。
- **Never invents events.** 没有来源的日期不列入。如有缺口，标注 `[gap: no source for events between X and Y]`。
- **Never guarantees completeness.** 时间线反映已审阅的来源；新来源可能增加条目。
- **Legal assertions carry provenance tags.** 如 matter.md 说"对方违约"，时间线记录"X 于 Y 日未按合同交付"，来源标注为 `[matter.md — theory, not fact]`。

## Writing the output

写入 `matters/[slug]/chronology.md`。

## Close with the next-steps decision tree

以 practice profile `## Outputs` 中的 next-steps decision tree 结束。
自定义选项以适应本 skill 刚产生的内容。

## What this skill does not do

- 运行 privilege review。它要求 privilege posture 已被确定。
- 决定案件理论。它读取 matter.md 中的理论；理论变更需要 matter-update。
- 替代法律研究。来源标注中的 `[model knowledge — verify]` 和 `[inference — verify]` 是待验证项，不是已确认项。
- 生成可提交文件。Statement-of-Facts variant 是草稿，需经 attorney review。
