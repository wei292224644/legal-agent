---
name: demand-draft
description: >
  基于完成的 intake 起草律师函/索赔函，输出行内审查版本和 post-send checklist。
  在起草前运行强制 gate checklist。
  发送前必须经 attorney review。
---

# /demand-draft

1. 读取 `demand-letters/[slug]/intake.md`。
2. 运行 pre-draft gate — 强制 checklist。
3. 遵循下方起草规则。
4. 生成草稿 + post-send checklist。
5. 向用户确认："这是草稿。不是可直接发送的信件。 attorney review 后才能发送。"

---

# Demand Draft

## Purpose

把 intake 中 capture 的审慎思考转化为一封精确、可追踪来源、风险受控的函件。

## Load context

- `demand-letters/[slug]/intake.md` — 完整 intake，含 posture、strategic block（或跳过标记）
- `practice profile` → house style、特权标记规范、签字权限

## Pre-draft gate — mandatory checklist

在写任何正文之前，逐一确认以下事项。每个都必须被 engage：

- [ ] **Privilege filter.** intake.md 中的特权过滤器是否被尊重？内部分析、未验证事实、策略推理是否被排除？
- [ ] **Admission risk.** 函件中是否有任何内容可能被对方后来用作事实或责任承认？
- [ ] **Accord-and-satisfaction risk.** 此函件是否冒险无意中满足或声称接受另一项索赔？
- [ ] **Settlement-communication posture.** 此函件是否受和解沟通保护？标记和 structuring 是否支持该 posture？
- [ ] **Privilege waiver scan.** 函件是否可能放弃相关分析的特权？（如包含内部评估、先前和解讨论）
- [ ] **Tone posture.** 语气是否与 intake 中 capture 的 tone（克制/坚定/强硬）一致？是否考虑了关系保护？
- [ ] **Factual accuracy.** 每个事实是否可追溯到 intake 中的来源？未验证的事实是否有 `[VERIFY]` 标记？

**Do not proceed until each is engaged.**

如果 strategic block 被跳过，pre-draft gate 仍然运行，但依赖 strategic block 答案的部分获得 `[SME VERIFY: leverage/tone/privilege not captured in intake]` 标记。
同时提示用户：
> Strategic block 在 intake 中被跳过。草稿可用，但以下部分标记为需验证：[列表]。
> 你想在继续前完成 strategic block 吗？

## Record fidelity rules

- **Verbatim quotes must be exact.** 如引用合同条款、往来函件或对方陈述，必须精确。如无法获取精确文本，
  不带引号地意译，并标注 `[verify exact quote]` 占位符。
- **Pinpoint cites must support the whole proposition.** 引用条款时必须支持所主张的全部命题，而非仅部分。
- **No silent supplementation.** 不从网络搜索或模型知识中静默补充缺失的事实或法律依据。
  如有缺口，标注 `[CITE:___]` 或 `[RULE TO VERIFY]`。

## Drafting rules

1. **Specificity over adjectives.** 不要写"严重违约"；写"未按合同第3.2条于2024年3月1日前交付货物，逾期47天"。
2. **Facts traceable to sources.** 每个关键事实应能追溯到 intake 中的具体来源（合同条款、邮件日期、证人陈述）。
3. **`[CITE:___]` placeholders — never invented.** 如需引用法规、判例或合同条款但具体引用未知，
   使用 `[CITE:___]` 占位符。绝不编造条款编号或判例名称。
4. **Consequence language matches tone posture.**
   - `relationship-preserving`："如在上述期限内未能解决，我们可能不得不考虑进一步的法律选择。"
   - `measured`："如未在 [日期] 前收到满意答复，我们将依法采取进一步行动，包括但不限于向 [管辖法院/仲裁机构] 提起诉讼/仲裁。"
   - `scorched-earth`："如未立即纠正，我们将毫不犹豫地行使一切法律权利，并寻求所有可用的救济，包括禁令、损害赔偿和费用。"
5. **Inline alternative phrasings.** 如对某句话的措辞有顾虑，提供备选：
   `[Alt: "..." — softer; "..." — firmer]`
6. **No settlement discussion unless intended.** 如函件不是和解沟通，不要包含和解提议或"我们愿意讨论"等表述，
   以免削弱立场或产生和解沟通保护争议。
7. **Privilege markings per house style.** 如函件为内部工作产品草稿，标注 `[WORK-PRODUCT / 律师工作成果]`。
   外部交付物不带工作产品头。

## 输出格式

### 1. Draft（in-chat review version）

```markdown
[WORK-PRODUCT HEADER — 仅内部版本]

# [函件类型]: [标题]

[发件人信息]
[日期]

[收件人]

Re: [主题]

Dear [Name]:

[引言 — 身份、目的、一句话]

[事实陈述 — 时间顺序、可追溯来源、无情绪化措辞]

[法律依据 — 具体条款、带 `[CITE:___]` 占位符如需要]

[诉求 — 分条、具体、附期限]

[法律后果提示 — 与 tone posture 匹配]

[结尾]

Sincerely,
[Signer]

---

## Draft notes

- Tone posture: [克制/坚定/强硬]
- Response window: [N 天]
- Marking: [无/不影响和解/...]
- `[CITE:___]` placeholders: [列表]
- `[VERIFY]` markers: [列表]
- Privilege filters applied: [是/否 — 如否，标记风险]
```

### 2. Post-send checklist

函件发送后（经 attorney review 并实际发送），生成 `checklist.md`：

```markdown
# Post-Send Checklist: [slug]

## Sent
- [ ] 发送日期: ___________
- [ ] 发送方式: ___________
- [ ] 签收/送达证明: ___________

## Follow-up
- [ ] 回复截止日期: ___________
- [ ] Calendar reminder set: ___________
- [ ] 未回复时的升级路径: ___________

## Materiality
- [ ] 是否构成需创建 matter 的重大事件？
- [ ] 保险是否已通知（如 practice profile 要求 pre-demand tender）？

## Records
- [ ] 发送副本存档
- [ ] 原稿 + 最终版 + 发送版已区分存档
```

## Materiality assessment + matter creation offer

发送后评估：此函件是否 material enough to create a matter？
如果是，提供运行 `/matter-intake [name]`。

## Critical warnings

- **草稿不是可直接发送的信件。** Sending starts clocks on disputes, counterclaims, statutes.
- **Attorney review required.** 外部交付物不带 work-product header；内部文件带。
- **Citations need verification.** `[CITE:___]` 占位符必须在发送前填充，并通过法律研究工具验证来源归属。
  不通过网络搜索或模型知识静默补充。
- **非律师角色 gate.** 如角色为非律师，在标记为发送前需要显式确认 attorney review，
  并可选提供 1-page summary brief 供 attorney consultation。

## What this skill does not do

- 发送函件。它起草；用户/律师在 review 后发送。
- 替代 attorney judgment。Pre-draft gate 是 checklist，不是审批。
- 验证引用。`[CITE:___]` 占位符需要后续法律研究填充。
- 在 privilege 未确定时生成外部交付物。
