---
name: matter-intake
description: >
  接收新案件 — 统一问题覆盖身份识别、利益冲突、来源、风险分流、
  重要性、外部律师、负责人、证据保全和关键日期；
  生成 matter.md、history.md 并在 _log.yaml 中追加结构化行。
  当用户说"新案件"、"接入这个案子"或想把新案件纳入案件组合时使用。
---

# /matter-intake

1. 加载当前事务所配置（ContextStore 中的 practice profile）→ 风险校准（用于分流）、利益冲突方法。
2. 遵循下方工作流和参考。
3. 运行统一接入：身份识别、利益冲突检查、来源、风险分流、重要性、外部律师、内部负责人、证据保全、关键日期、初始立场。
4. 根据案件名称生成 slug（小写、连字符、年份）。
5. 创建 `matters/[slug]/matter.md` — 完整叙述性接入。
6. 创建 `matters/[slug]/history.md` — 以接入为第一条记录。
7. 追加结构化行到 `matters/_log.yaml`。
8. 向用户确认："这是我要写入的记录 — 有需要修改的吗？"

---

# Matter Intake

## Purpose

每个新案件都经过相同的接入流程，这样案件组合才能保持可比性。
`_log.yaml` 中的统一行让状态汇总成为可能。
`matter.md` 中的叙述捕捉了结构化行无法记录的内容。
在此处初始化的 history 文件将成为事件记录。

## Load context

- `practice profile`（ContextStore）— 风险校准（分流阈值、重要性、和解阶梯）、利益冲突方法、利益相关方、外部律师名录。
- `matters/_log.yaml` — 确认 slug 唯一性。

## The intake

### 1. Identification

- 案件名称（常用称谓，如"张三诉某公司 2026"）
- 相对方
- 案件类型：`合同 | 劳动 | 知识产权 | 行政监管 | 调查 | 产品责任 | 其他`
- 我方角色：`原告 | 被告 | 申请人 | 被申请人 | 被调查方`
  - 如果 practice profile 中的 `## Side` 是 `原告`、`被告` 或"两者 — 默认 X"变体，从该默认值预填角色并确认。
    如果 `## Side` 是 `因案而异`，则直接询问。绝不静默假设 practice profile 未设定的立场。
  - 角色驱动下游 skill：原告立场案件将风险分流导向案件价值 / 风险代理经济分析；
    被告立场案件将风险分流导向风险敞口 / 准备金 / 保险通知。
- 管辖（法院、仲裁机构或监管机关）

### 2. Conflicts check

在继续之前，按 practice profile → Conflicts clearance 运行利益冲突步骤。

- **Status:** `已清 | 待处理 | 未运行 | 放弃`
- **Method:** 与 practice profile 声明一致（`公司法务部 | 外部律所 | 系统检查 | 非正式 | 其他`）。
  如果声明方法是 `非正式`，请说明 — 记录仍然 capture 了律师判断检查这一基础。
- **Cleared by:** 姓名 / 团队 / 律所
- **Cleared date:** YYYY-MM-DD
- **Checked against:** 运行的具体名称/实体简短列表（相对方、已知关联方、对方律师如已知、关键证人）。简即可；"无"不行。
- **Notes:** 任何被标记但已清除的事项（如"我方董事 Smith 于 2019–2021 年同时在相对方董事会任职 — 已清除，因与本案无时间重叠"）。

Behavior by status:

- `已清` → 继续。
- `待处理` → 继续接入；在 `matter.md` 和 log 行中显著标记利益冲突尚未解决；
  每次 `/matter-update` 和 `/portfolio-status` 都重新显示，直到解决。
- `放弃` → 罕见；需要利益冲突放弃理由书（撰写放弃书超出本 skill 范围 — capture 存在放弃书、谁签署、存放位置）。
- `未运行` → **停止。这是一个 gate。** 在利益冲突状态解决之前，本 skill 不会创建 `matter.md`、`history.md` 或 `_log.yaml` 条目。三条可接受路径：

  **Path 1 — 立即运行利益冲突。** 暂停本次接入。按 practice profile Conflicts clearance 清理。返回 `status: cleared` 或 `status: waived` 及理由。

  **Path 2 — 标记待处理并指定负责人 + 截止日期。** 仅在 practice profile Conflicts clearance 声明允许并行接入时允许。Capture：谁正在运行利益冲突、预计何时返回、正在检查哪些实体。接入继续；matter 行携带 `conflicts.status: pending`；`/portfolio-status` 每次运行都标记；`/matter-update` 重新提示直到解决。

  **Path 3 — 带记录理由绕过。** 仅在用户明确确认绕过时才允许。记录在 `conflicts.override` 中：

  ```yaml
  conflicts:
    status: not-run               # 保持原样
    override:
      by: [用户姓名]
      date: [YYYY-MM-DD]
      rationale: [利益冲突被绕过的原因 — 永久记录；不会自动过期]
  ```

  该字段在每次 `/portfolio-status`、每次 `/matter` briefing 和每次 `/matter-update` 中可见，直到被移除。
  它不会被 skill 移除 — 仅在利益冲突实际清理后由用户显式编辑 `_log.yaml` 移除。

  **不要静默继续。** "我稍后再做"不是可接受的回应。Path 1/2/3 必须选择其一，且选择被记录在案。

本步骤不是由 skill 判断利益冲突是否存在 — 那是用户/律所的判断。
它是确保检查已发生且记录反映了这一点。

### 3. Source

如何到达的？
- `律师函 | 起诉状送达 | 传票 | 监管问询 | 内部报告 | 诉前威胁`
- *种子文档机会：* "如果你有启动文档（起诉状、律师函、传票），请附上或分享路径。它会让接入更精准。"

### 4. Risk triage — against house calibration

- Severity: 高 | 中 | 低（参考 practice profile severity bands）
- Likelihood: 高 | 中 | 低（参考 practice profile likelihood bands）
- Resulting risk rating（按矩阵）: 高 | 中 | 低 | 严重
- 损害赔偿范围（最佳估计）
- 非金钱风险（禁令？同意令？公开曝光？先例？）

如果 practice profile 中的风险校准较薄，不要假装精确。使用用户的直觉并标注薄度。

### 5. Materiality

按 practice profile 中的 house thresholds：
- `已计提 | 已披露 | 监控中 | 无`
- 如果 `已计提`：计提金额及财务部门是否已通知
- 如果 `已披露`：申报文件和脚注位置

### 6. Outside counsel

- 律所
- 主办合伙人
- **主办合伙人邮箱**（`/oc-status` 用于起草状态请求邮件）
- 委托协议状态：`已签署 | 待签署 | 无`
- 预算授权：金额和审批人
- *种子文档机会：* "委托协议路径，如已签署。"

如果风险为中等或更高且未分配外部律师 — 标记它。

### 7. Internal owners

按 practice profile landscape — 哪些内部利益相关方参与？
- 业务负责人
- HR 伙伴（如涉及劳动）
- 公关联系人（如声誉风险）
- 信息安全官（如涉及数据或网络安全）
- 其他

### 8. Legal hold

- 已签发？如是：日期、范围、保管人（姓名列表）。
- 下次刷新日期（默认：签发后六个月；按案件调整）。
- 如未签发且本案为活跃诉讼或合理预期：紧急标记；提供在接入完成后运行 `/legal-hold [slug] --issue`。
- *种子文档机会：* "保全通知，如已签发。"

### 9. Key dates

- 回应截止日期（答辩、异议、反对）
- 下次开庭 / 会议
- 诉讼时效截止（如适用）
- 任何监管截止日期

### 10. Initial posture

一段话理论：
- 我们的故事是什么？
- 他们的故事是什么？
- 关键转折点事实是什么？
- 初始立场：`对抗 | 和解 | 调查 | 观望`

## Writing the outputs

### Slug

小写、连字符、年份在后。示例：`zhang-san-v-mou-gong-si-2026`、`lao-dong-jiu-fen-li-si-2026`、`shi-chang-jian-guan-wen-xun-2026`。

写入 `_log.yaml` 前确认 slug 唯一性。

### `matters/[slug]/matter.md`

```markdown
[WORK-PRODUCT HEADER — 按 practice profile ## Outputs — 因角色而异]

# [案件名称]

**Slug:** [slug]
**Opened:** [YYYY-MM-DD]
**我方角色:** [原告/被告/等]
**Status:** [status]

---

## Identification

[相对方、管辖、案件类型、来源]

## Conflicts

**Status:** [已清 / 待处理 / 未运行 / 放弃]
**Method:** [公司法务部 / 外部律所 / 系统检查 / 非正式 / 其他]
**Cleared by:** [姓名]
**Cleared date:** [YYYY-MM-DD]
**Checked against:** [运行实体]
**Notes:** [任何已清除的标记、放弃书引用如适用]

## Risk triage

**Severity:** [band] — [原因，引用 house severity 定义]
**Likelihood:** [band] — [原因]
**Risk rating:** [高/中/低/严重]
**Exposure:** [金额范围 + 非金钱]

## Materiality

[已计提/已披露/监控中/无 — 含计提金额、披露位置或"无"的理由]

## Outside counsel

[律所、主办、委托状态、预算]

## Internal owners

[利益相关方及每人参与原因]

## Legal hold

[状态、日期、范围]

## Key dates

[列表]

## Initial theory

[一段话：我们的故事、他们的故事、关键事实、初始立场]
`[SME VERIFY — intake 时的理论是工作假设；在任何提交或实质性沟通前与外部律师确认]`

## Open questions

[任何尚未知晓但重要的事项 — 如"保险通知待处理"、"是否覆盖 X 尚不清楚"]

---

## Seed documents

| 文档 | 路径 / 指针 |
|---|---|
| [如起诉状] | [路径或"尚未分享"] |
```

### `matters/[slug]/history.md`

用接入作为第零条记录来初始化 history 文件：

```markdown
# History: [案件名称]

追加式事件记录。最新在上。

---

## [YYYY-MM-DD] — 案件开启

[来源、谁带入、初始分流摘要、外部律师分配、证据保全是否签发。]
```

### Append to `matters/_log.yaml`

按 schema 添加一行。示例：

```yaml
- id: zhang-san-v-mou-gong-si-2026
  name: "张三诉某公司"
  type: 劳动
  role: 被告
  counterparty: "张三"
  jurisdiction: "北京市朝阳区劳动仲裁委员会"
  status: active
  stage: 答辩期
  source: 仲裁申请送达
  outside_counsel:
    firm: "某律所"
    lead: "李律师"
    email: "li@example.com"
    engagement: signed
  conflicts:
    status: cleared
    method: 公司法务部
    cleared_by: "王法务"
    cleared_date: 2026-04-20
    override:
      by: null
      date: null
      rationale: null
  risk: 高
  materiality: 已计提
  exposure_range: "20万–50万元"
  internal_owners:
    business_lead: "赵经理"
    hr_partner: "孙HR"
    comms_contact: null
  legal_hold:
    issued: true
    issued_date: 2026-02-15
    scope: "销售部 2023–2026"
    custodians: ["赵经理", "陈销售"]
    last_refresh: 2026-02-15
    next_refresh: 2026-08-15
    released: null
  related_matters: []
  opened: 2026-04-20
  next_deadline: 2026-05-15
  last_updated: 2026-04-20
  path: matters/zhang-san-v-mou-gong-si-2026/
```

## Confirm before writing

向用户展示该行和 matter.md 内容：

> 这是我要写入的内容。在提交前标记任何错误或薄弱之处。

## Close with the next-steps decision tree

以 practice profile `## Outputs` 中的 next-steps decision tree 结束。
自定义选项以适应本 skill 刚产生的内容 — 五个默认分支
（起草 X、升级、获取更多事实、观望、其他）是起点，不是锁定。
树是输出；律师选择。

## What this skill does not do

- **自行运行利益冲突检查。** 它记录结果、状态、方法和检查的实体。
  实际清理发生在 practice profile 声明的系统（或判断）中。
  如果用户说"已清理"，skill 采信并 capture 元数据。
- 决定初始理论。它 capture 用户所说；不发明理论。
- 签发证据保全。标记缺失。由用户签发。
