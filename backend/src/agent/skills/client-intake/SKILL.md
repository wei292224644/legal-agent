---
name: client-intake
description: >
  结构化客户接待 — 自动生成交谈摘要、识别跨领域问题、标记利益冲突、分类分流。
  不决定案件接受。输出结构化会谈摘要。
---

# /client-intake

1. 加载 practice profile → 业务领域、管辖、监督风格。
2. 遵循下方工作流和参考。
3. 运行领域路由 + 领域特定 intake + 跨领域问题识别 + 利益冲突标记 + 分流分类。
4. 生成结构化会谈摘要。
5. 如有截止日期，输出可直接粘贴的 `/deadlines --add` 块。

---

# Client Intake

## Purpose

加速信息收集，不是替代 lawyering。结构化接待对话，生成交谈摘要，
识别客户未意识到的关联法律问题，标记利益冲突，分类紧急程度。

## Load context

- `practice profile`（ContextStore）— 业务领域、管辖、监督风格
- `guides/<practice-area>.md` — 如存在领域特定指南

## Workflow

### Step 1: Practice area routing

客户描述问题；系统映射到法律类别。

默认领域模板：

**劳动（Employment）**
- 当事人身份：劳动者 / 用人单位
- 关系建立：入职日期、合同签订、岗位
- 争议触发：解除/终止日期、原因、通知方式
- 诉求：赔偿金额 / 恢复劳动关系 / 其他
- 证据：合同、工资记录、考勤、解除通知

**合同（Contract）**
- 合同类型：买卖 / 服务 / 借款 / 租赁 / 其他
- 签订情况：书面 / 口头 / 电子
- 履行情况：已履行 / 部分履行 / 未履行
- 争议触发：违约行为、日期、通知
- 诉求：履行 / 解除 / 赔偿 / 其他
- 证据：合同、付款记录、履行凭证、沟通记录

**侵权（Tort）**
- 损害类型：人身 / 财产 / 名誉 / 知识产权
- 侵权行为：时间、地点、行为人
- 损害结果：医疗费 / 财产损失 / 精神损害
- 因果关系：客户如何证明行为与损害之间的因果
- 诉求：赔偿金额 / 停止侵权 / 赔礼道歉
- 证据：现场记录、医疗记录、损失评估、沟通记录

**家事（Family）**
- 关系类型：婚姻 / 继承 / 抚养 / 赡养
- 当事人：配偶 / 子女 / 父母 / 其他亲属
- 财产情况：房产、车辆、存款、债务
- 争议焦点：离婚 / 抚养权 / 财产分割 / 继承份额
- 诉求：具体财产分配 / 抚养安排 / 赡养费
- 证据：结婚证、房产证、银行流水、聊天记录

**行政（Administrative）**
- 行政主体：具体行政机关
- 行政行为：处罚 / 许可 / 强制 / 征收
- 程序情况：是否告知、是否听证、是否送达
- 诉求：撤销 / 变更 / 确认违法 / 赔偿
- 时效：是否已过复议期 / 诉讼期
- 证据：行政决定书、送达回证、沟通记录

如问题不匹配默认模板，使用通用模板并标注 `[area: generic]`。

### Step 2: Area-specific intake

使用匹配领域的模板引导客户陈述。不是机械提问 — 根据客户回答自适应追问。

### Step 3: Cross-area issue spotting

在客户陈述过程中，监听是否涉及**跨领域信号**：

| 信号关键词 | 可能涉及的关联领域 | 需追问 |
|-----------|------------------|--------|
| 工伤、受伤、事故 | 劳动 + 人身损害赔偿 + 社保行政 | 工伤认定情况、伤情鉴定 |
| 竞业限制、商业秘密 | 劳动 + 知识产权 | 保密协议内容、竞业限制补偿金 |
| 股权、期权、分红 | 劳动 + 公司股权纠纷 | 持股协议、行权条件 |
| 孕妇、产期、哺乳 | 劳动 + 妇女权益保护 | 解除时间是否在"三期" |
| 公司注销、破产 | 劳动/合同 + 破产清算 | 注销进度、债权申报 |
| 债务、借款、担保 | 合同 + 债权债务 | 债务性质、是否与公司有关 |
| 房产、拆迁、继承 | 家事/合同 + 物权 | 是否为主要诉求 |
| 行政处罚、调查 | 行政 + 刑事 | 是否涉及刑事责任 |
| 网络、数据、平台 | 合同 + 数据合规 | 数据处理方式、用户协议 |

**规则：不解决跨领域问题 — 只 surface 它。** 在摘要中标注 `[cross-area: 领域]`，
并建议后续由具备该领域能力的律师 review。

### Step 4: Conflict check flags

标记潜在利益冲突：

- **相对方利益冲突**：相对方是否为当前或 former client？
- **关联方方面冲突**：相对方的关联方是否与我们有关联？
- **立场冲突**：我们是否在同一事项中代表过对方或相关方？
- **重复对手**：此相对方是否在多个案件中与我们对抗？

**规则：不解决冲突 — surface 它。** 在摘要中标注 `[conflict flag: 描述]`，
并建议运行 formal conflicts check。

### Step 5: Triage classification

将案件分类为：

- **紧急（Urgent）**：时效即将届满、人身安全受威胁、证据可能灭失、需立即保全
- **时间敏感（Time-sensitive）**：有明确近期截止日期、对方正在采取行动、需快速响应
- **标准（Standard）**：常规法律问题，无即时截止日期
- **可能超出范围（May be out of scope）**：明显不属于本所业务领域、 jurisdictional 障碍、或证据严重不足

### Step 6: Supervision flag check

按 practice profile 中的监督风格：
- 是否需要 supervising attorney review 后才能向客户承诺任何事项？
- 是否需要学生在首次面谈后提交书面摘要？
- 案件复杂度是否超出学生独立处理范围？

### Step 7: Deadline handoff

如 surfaced 任何截止日期，输出可直接粘贴的 `/deadlines --add` 块：

```
/deadlines --add \
  --matter [slug] \
  --date YYYY-MM-DD \
  --type [仲裁/诉讼/行政/其他] \
  --description "..." \
  --urgent [true/false]
```

## Output format

```markdown
═══════════════════════════════════════════════════════════════════════
  PRIVILEGED AND CONFIDENTIAL — ATTORNEY WORK PRODUCT
  本摘要是律师工作成果，受律师-委托人特权保护。
  未经授权不得向第三方披露。
═══════════════════════════════════════════════════════════════════════

# Client Intake Summary: [客户姓名]
**Date:** [date] | **By:** [律师/学生] | **For:** [Supervising Attorney]

---

## Bottom line

[一句话：案件类型 + 紧急程度 + 是否接受（待决定）]

## Client's narrative

[客户陈述的客观摘要，按时间顺序，保留客户原话的关键短语]

## Legal issues identified

1. **[Primary issue]** — [领域]
   [一句话描述]
   `[model knowledge — verify]`

2. **[Secondary issue]** — [领域]
   [一句话描述]
   `[model knowledge — verify]`

3. **[Cross-area issue]** — [关联领域]
   [触发信号和为什么可能相关]
   `[model knowledge — verify]`

## Key facts table

| Fact | Source | Subject | Verified |
|---|---|---|---|
| ... | client statement | 当事人 | [ ] |
| ... | document mentioned | 对方 | [ ] |

## Conflict check flags

- [ ] **[Flag 1]** — [描述] — [建议 action]
- [ ] **[Flag 2]** — [描述] — [建议 action]

## Triage

**Classification:** 紧急 / 时间敏感 / 标准 / 可能超出范围
**Rationale:** [一句话]
**Next action:** [具体下一步 + 负责人 + 截止日期]

## Deadlines surfaced

1. **[日期]** — [事项] — `[VERIFY: 需与客户确认具体日期]`
2. ...

## Jurisdictional notes

- 管辖：[法院/仲裁机构]
- 时效状态：[安全 / 临近 / 已过 — 如临近则标注 `[URGENT]`]
- 法律适用：[如存在法律选择问题]

## Supervision flags

- [ ] 需要 supervising attorney review
- [ ] 超出学生独立处理范围
- [ ] 需要领域专家 consult

## Verification prompts for the attorney

- [ ] 确认 [事实] — 客户说法 vs 文档记录
- [ ] 确认 [法律] — `[model knowledge — verify]` 标注项需法律研究验证
- [ ] 确认 [管辖] — 是否正确识别了管辖法院/仲裁机构
- [ ] 确认 [冲突] — 利益冲突标记是否已 formal clear

═══════════════════════════════════════════════════════════════════════
```

## Guardrails

- **Does NOT decide case acceptance.** 学生/律师分析，合伙人/主管决定。
- **Don't resolve the conflict — surface it.** 利益冲突标记是提示，不是结论。
- **Privilege warning on every output.** 每次输出头部标注特权声明。
- **Provenance tags required on all legal citations.** 所有法律引用标注来源。
- **`[VERIFY]` marker for computed deadlines.** 计算得出的截止日期标注 `[VERIFY]`；
  仅当文档中直接声明时才使用实际日期。

## Close with the next-steps decision tree

以 practice profile `## Outputs` 中的 next-steps decision tree 结束。
自定义选项以适应本 skill 刚产生的内容。

## What this skill does not do

- **决定案件接受。** 它加速信息收集；接受/拒绝由 supervising attorney 决定。
- **提供法律意见。** 摘要中的法律 issue 识别是初步的，不构成意见。
- **替代与客户的持续对话。**  intake 是起点，不是终点。
- **运行 formal conflicts check。** 它标记潜在冲突；实际清理在外部系统中进行。
