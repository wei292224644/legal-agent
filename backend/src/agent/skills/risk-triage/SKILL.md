---
name: risk-triage
description: >
  快速模式匹配分流 — 用于客户/律师在会谈中抛出的即时法律问题，
  目标一分钟内响应。输出 ✅ 无大碍 / ⚠️ 需要关注 / 🛑 暂停。
  运行陷阱检查识别隐藏问题。
---

# /risk-triage

1. 加载 practice profile → 风险校准表。
2. 应用分流（对照校准表匹配）。
3. 运行陷阱检查（trap check）识别隐藏问题。
4. 输出：✅ 无大碍 / ⚠️ 需要关注 / 🛑 暂停。

---

# Risk Triage

## Purpose

快速回答"这有没有问题"。不是完整分析，是模式匹配 + 隐藏问题扫描 + 方向指引。
目标是让律师在会谈中即时获得风险方向判断，而不是让客户等待。

## Load context

- `practice profile` → 风险校准（severity bands、likelihood bands、materiality thresholds）
- 当前 matter context（如有活跃 matter）

## The triage

### Step 1: Match against calibration table

对照 practice profile 中的风险校准表，判断陈述/问题落在哪个 band：

| 输入特征 | 初步评级 |
|---------|---------|
| 纯法条查询、无具体事实 | ✅ 无大碍 |
| 涉及具体事实，但规则清晰、结果可预期 | ✅ 无大碍 |
| 涉及具体事实，规则有争议或事实有缺口 | ⚠️ 需要关注 |
| 涉及多个法律领域交叉 | ⚠️ 需要关注 |
| 可能导致重大不利后果（大额赔偿、刑事责任、程序性失权） | 🛑 暂停 |
| 时效即将届满或关键期限临近 | 🛑 暂停 |

### Step 2: Trap check — hidden issues

对表面简单的陈述运行陷阱检查：

**Trap 1: 数据/隐私流向**
- 信号：提及第三方平台、SaaS、外包、数据处理
- 追问："什么数据流向了他们？有没有数据出境？"
- 如触发 → 升级至数据合规 review

**Trap 2: 自动续费 / 默认勾选**
- 信号：提及用户协议、服务条款、自动扣款
- 追问："用户是否被明确告知？退出机制是否便利？"
- 如触发 → 升级至消费者权益/合规 review

**Trap 3: AI/算法决策**
- 信号：提及智能推荐、自动审核、算法评分
- 追问："是否有算法备案？是否涉及自动化决策的告知义务？"
- 如触发 → 升级至算法合规 review

**Trap 4: 对公承诺 / 公开声明**
- 信号：提及对外宣传、白皮书、官网声明、社交媒体
- 追问："这些声明是否有证据支持？是否构成要约或误导？"
- 如触发 → 升级至广告合规/虚假宣传 review

**Trap 5: 跨境因素**
- 信号：提及境外主体、外币、跨境交易、外国法律
- 追问："管辖条款怎么约定的？适用法律是什么？有没有出口管制或制裁风险？"
- 如触发 → 升级至跨境合规 review

**Trap 6: 劳动关系伪装**
- 信号：提及外包、灵活用工、合作关系、自由职业者
- 追问："实际管理方式是否符合劳动关系认定标准？（人格从属性、经济从属性、组织从属性）"
- 如触发 → 升级至劳动合规 review

**Trap 7: 刑民交叉**
- 信号：提及欺诈、伪造、侵占、挪用、税务、走私
- 追问："是否已有行政调查或刑事立案？"
- 如触发 → 标记刑事风险，建议立即评估

### Step 3: Destination check — privilege before output

输出前检查：
- 本次响应对话是否在 privilege 保护范围内？
- 如果用户是在公共频道/非律师在场/可能对外转发 — 降级输出，移除具体策略和内部评估。

### Step 4: Matter context check

如果存在活跃 matter：
- 本次 triage 是否与已知 matter 相关？如是，attach 到 matter 档案。
- 如无关且可能构成新 matter，提示是否运行 `/matter-intake`。

## Output format

```
[✅ 无大碍 | ⚠️ 需要关注 | 🛑 暂停]

一句话结论：[评级和原因]

[如 ⚠️：]
需要关注什么：...
预计需要多长时间：...
建议下一步：...

[如 🛑：]
需要立即行动：...
应当联系谁：...
时间敏感度：...
```

## Tone directive

"Fast, direct, helpful. The client is not asking for a lecture."
目标："你是人们愿意问的律师，不是他们绕开的那位。"

- 一分钟内给出方向
- 不要法条堆砌
- 如果答案是"没问题"，直接说，不要附 500 字免责声明
- 如果答案是"需要关注"，说清楚关注什么、为什么、下一步找谁

## Close with the next-steps decision tree

以 practice profile `## Outputs` 中的 next-steps decision tree 结束。
自定义选项以适应本 skill 刚产生的内容。

## What this skill does not do

- 替代完整法律分析。它是 triage，不是 opinion。
- 预测结果。评级是基于模式和校准的快速判断，不是预测。
- 处理需要深度研究的复杂问题。⚠️ 和 🛑 的下一步通常是运行更深入的 skill 或转交律师。
- 在 privilege 不确定时输出敏感内容。Privilege check 失败 = 输出降级。
