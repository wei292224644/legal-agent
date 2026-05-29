---
name: demand-intake
description: >
  律师函/索赔函起草前的预写情境收集 — 当事人、事实、法律依据、筹码、
  BATNA、特权过滤器 — 写入结构化 intake.md，供 demand-draft skill 读取。
  当用户准备发函、需要在起草前收集情境，或 capture 付款催告、违约/补救通知、
  停止侵权、劳动解除、证据保全等情境时使用。
---

# /demand-intake

1. 加载 practice profile → 律师函实践、风险校准、house style。
2. 遵循下方工作流和参考。
3. 运行自适应 intake（核心 8 项必问；策略块在重大或 `--full` 时展开）。
4. 根据标题 + 相对方 + 年月生成 slug。
5. 写入 `demand-letters/[slug]/intake.md`。
6. 向用户确认："Intake 已保存。准备好后运行 `/demand-draft [slug]`。"

---

# Demand Intake

## Purpose

起草是下游。价值在预写 — 强制提出粗心函件会跳过的问题。
筹码、BATNA、下行容忍度、特权过滤器、实际受众。
一封没有思考这些问题就发出的律师函，比不发更糟。

## Load context

- `practice profile` → 律师函实践（保险通知时机、创建案件的材料性阈值、任何种子文档模板）、
  landscape（相对方类型、重复对手模式）、风险校准（用于预估计材料性）、house style。
  **语气、合规期限、标记、签署人不是 practice-level 默认值 — 它们在下方 `## Posture for this matter` 步骤中按案件设定。**

## Flags

- `--full` → 无论材料性启发式如何，都运行完整 intake（适用于希望每次都彻底的律师）

## The intake

### Posture for this matter（先问，在 core 之前）

> **Posture for this matter.** 律师函的语气和条款是 case-by-case，不是 practice default。询问：
> - **Tone:** 克制 / 坚定 / 强硬？（取决于关系、金额、诉讼可能性）
> - **Response window:** 考虑到索赔，什么是合理的？（付款催告常见 14 天；补救 30 天；停止侵权 7 天 — 但合同或规程可能有规定）
> - **Marking:** 这是否需要"不影响和解"或"除费用外不影响和解"标记？（和解沟通需要；权利主张通常不需要；管辖很重要 — 如不确定则询问）
> - **Signer:** 你、客户、法务总监、受托律师/顾问？
>
> 不要假设。如 matter 文件中有先前的律师函往来，阅读它们 — 它们确立了语域。

将答案记录在 intake 的 `## Posture` 部分中，放在 `## Parties` 之前。
这些答案主导 intake 的其余部分和下游草稿 — 如用户留空任何一项，不要回退到 practice-level default；再次询问。

### Core — always asked（8 个问题）

**1. Demand type**
`payment | breach-cure | cease-desist | employment-separation | preservation | other`

**2. Parties**
- **Sender:** 我方（如多实体则具体实体）
- **Recipient:** 相对方 — 名称、实体、地址
- **Recipient audience:** 谁实际阅读（法务？CEO？个人？内部律师？）
- **Relationship:** `客户 | 供应商 | 前员工 | 竞争对手 | 第三方 | 其他`

**3. Triggering event**
- 发生了什么、何时发生（日期重要 — 诉讼时效、通知期限）
- 可用证据（合同、邮件、记录、证人）

*种子文档机会："如果你能分享基础合同、往来函件或证据，草稿会显著更精准。"*

**4. Legal / contractual basis**
- 哪些条款 — 具体合同章节如适用
- 适用法律（管辖、法律选择条款）
- 依赖的法规或规则（占位符可接受 — 草稿会标记 `[CITE:___]`  anyway）

**5. Desired outcome**
- 具体请求。不是"解决" — 在 Y 日前支付 X 元；停止具体活动 Z；在 N 天内补救；返还具体财物。
- 如有多项请求，排序（主要 vs 替代）

**6. Deadlines**
- 驱动本次发函的外部截止日期（诉讼时效、持续损害窗口、商业事件）
- 律师函合规截止日期 — 给对方多长时间。使用上方 `## Posture for this matter` 中 capture 的 response window；
  不要回退到 practice-level default。

**7. Prior outreach**
- 此事是否已非正式提出？何时、由谁、以何种形式？
- 目前有任何回应吗？
- 为什么现在要升级为律师函？

**8. Distribution**
- 交付方式（询问；无 practice-level default）
- 签署人 — 上方 `## Posture for this matter` 中已 capture
- 抄送 — 内部利益相关方、保险公司（如按 practice-level tender-timing 规则在发函前通知保险）、律师

### Strategic — 在重大时询问，或 `--full` 时

材料性启发式：如以下任何一项为真，则询问策略块。

- Demand type 为 `cease-desist`、`breach-cure`、`employment-separation` 或 `preservation`
- 期望结果金额 ≥ practice profile 风险校准中的中等 severity band
- 相对方为客户、竞争对手或 practice profile landscape 中的 frequent adversary
- 用户使用了 `--full`

**显式跳过选项。** 当策略块被触发时，用户可以拒绝回答。直接询问：

> 按启发式这是重大律师函。策略块（筹码、BATNA、语气、特权过滤器）是预写价值所在。跳过它会产生更薄的草稿。
> - **现在回答** — 走策略块（5-7 分钟）
> - **部分回答** — 走你准备好的子集
> - **跳过** — 仅带核心块继续起草；我会在 intake 中标记 `strategic_block: skipped`

如用户选择 Skip，intake 文件记录：

```yaml
strategic_block: skipped        # answered | partial | skipped
skipped_reason: string | null   # 如用户提供了则 capture
```

草稿 skill 尊重跳过 — pre-draft gate 仍然运行，但依赖策略块答案的部分会获得
`[SME VERIFY: leverage/tone/privilege not captured in intake]` 标记。
`/demand-draft` 命令也会第二次提示，询问用户是否想在起草前完成策略块。

**9. Leverage and BATNA**
- 什么给了我们谈判筹码（合同权利、事实筹码、声誉、商业）
- 如果他们拒绝 — 我们是否准备诉讼？公开？接受较小结果？
- 他们可能的 BATNA — 他们的最佳选择是什么？（如他们认为我们不会起诉，函件就弱。）

**10. Downside tolerance**
- 如此事公开，声誉风险
- 先例风险 — 此函件是否会影响其他案件的格局？
- 监管/披露影响（这类争议是否会成为年报/半年报披露事项？）
- 保险影响 — 未通知保险就发送是否放弃承保？

**11. Tone posture**
- 上方 `## Posture for this matter` 中已 capture。此处，如用户选择了比事实似乎支持的更强语气，或比事实似乎支持的更弱语气，则 probe 权衡。
- 值得明确指出：强硬语气会烧毁关系。如你想保持商业关系但需要保护法律立场，`克制` 通常是正确选择。

**12. Settlement-communication posture**
- 研究适用 forum 的和解沟通保护（中国语境下无 FRE 408，但存在类似调解保密原则）。
  此函件是否应受保护的和解沟通？还是不应受保护的权利主张？
- 如受保护：草稿将包含和解沟通标记，并 structuring 实质（妥协讨论）而非仅标签来支持 posture。
- 保护依附于行为和情境，而非仅标签。标记是 belt-and-suspenders 选择。

**13. Privilege filters**
- 我们的内部分析中有什么绝对不能出现在函件中的？（未验证的事实、我们对我们案件的怀疑、策略推理、先前和解讨论）
- 一个措辞不当的句子可能放弃相关分析的特权。明确什么留在外面。

**14. Admission and accord-and-satisfaction risk**
- 函件中有什么对方后来可能定性为事实或责任承认的内容？
- 此要求是否冒险无意中满足（或声称接受）另一项索赔？
  （Accord-and-satisfaction：兑现标有"全额支付"的支票可以终结有争议的债务。）

## Writing the intake

### Slug

`[类型]-[相对方简称]-[yyyy-mm]`。确认在 `demand-letters/` 中的唯一性。

### `demand-letters/[slug]/intake.md`

```markdown
[WORK-PRODUCT HEADER — 按 practice profile ## Outputs — 因角色而异]

# Demand Intake: [标题]

**Slug:** [slug]
**Demand type:** [类型]
**Drafted by:** [律师]
**Opened:** [YYYY-MM-DD]
**Status:** intake | ready-to-draft | drafted | sent | closed
**Strategic block:** answered | partial | skipped
**Skipped reason:** [如适用]

---

## Posture

- **Tone:** [克制 / 坚定 / 强硬 — 附与关系和金额相关的一句话理由]
- **Response window:** [N 天 — 与索赔/合同/规程相关]
- **Marking:** [无 / 不影响和解 / 除费用外不影响和解 / 其他 — 附理由]
- **Signer:** [姓名 / 角色 — 你 / 客户 / 法务总监 / 受托律师]

*这是 intake 时 capture 的 per-matter posture。草稿 skill 从此处读取。*

---

## Parties

- **Sender:** [我方实体]
- **Recipient:** [相对方、实体、地址]
- **Recipient audience:** [谁阅读]
- **Relationship:** [类型]

## Triggering event

[发生了什么、何时、证据]

## Legal / contractual basis

[条款、适用法律、法规]

## Desired outcome

[按优先级排序的具体请求]

## Deadlines

- **External:** [诉讼时效、持续损害窗口]
- **Compliance:** [我们给对方多长时间]

## Prior outreach

[历史，最近在上]

## Distribution

- **Delivery:** [方式]
- **Signer:** [姓名/角色]
- **Copies:** [列表]

---

## Strategic (if applicable)

### Leverage & BATNA

[我方筹码、他们可能的回应]

### Downside tolerance

[声誉、先例、监管、保险]

### Tone posture

[关系保护 / 克制 / 焦土 — 附理由]

### Settlement-communication posture

[在 forum 中受保护或否 — 附推理。引用适用规则的主要来源。]

### Privilege filters

[绝对不能出现在草稿中的内容]

### Admission / accord-and-satisfaction risk

[标记的具体风险]

---

## Seed documents

| 文档 | 路径 |
|---|---|
| [基础合同] | [路径或"未分享"] |
| [先前往来函件] | [路径或"未分享"] |
| [证据] | [路径或"未分享"] |

---

## Materiality assessment

**Auto-heuristic says:** [material / immaterial — 附推理]
**User call:** [material / immaterial / TBD at post-send]
```

## Confirm before writing

向用户展示 draft intake。标记任何薄弱之处：

> 这是 intake。我注意到 [薄弱之处]。在保存前，有什么要补充的吗？

## Handoff to drafting

以以下结束：
> Intake 已保存。准备好后：`/demand-draft [slug]`

## Close with the next-steps decision tree

以 practice profile `## Outputs` 中的 next-steps decision tree 结束。
自定义选项以适应本 skill 刚产生的内容。

## What this skill does not do

- 起草函件。那是 `demand-draft` — 两步故意分开，以便律师可以在起草前暂停获取业务输入、外部律师咨询或保险通知。
- 决定是否发函。有些 intake 会议以"其实，别发了 — 我们直接谈"结束。这是有效结果；intake 记录仍有价值。
- 运行利益冲突检查。如相对方是客户或已知实体，标记应在发送前按 practice profile 清理利益冲突 — 但检查本身位于 matter-intake 工作流或本 skill 之外。
