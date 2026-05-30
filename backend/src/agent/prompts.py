"""集中管理所有 LLM 提示词（Prompt）。

所有 Agent 的系统提示、角色提示、任务提示统一在此封装为函数，
便于运营调整和产品迭代，不要在各 Agent 脚本中重复定义或直接使用字符串常量。
"""


def build_profile_prompt(
    speaker: str,
    text: str,
    history: list,
    existing_profile: dict[str, dict[str, str]],
) -> str:
    """法律事实提取提示（窗口+已知事实）。"""
    from models.utterance import Utterance

    # 格式化最近对话窗口
    history_lines = []
    for utt in history:
        if isinstance(utt, Utterance):
            label = utt.speaker or "unknown"
            history_lines.append(f"[{label}] {utt.text}")
        else:
            history_lines.append(str(utt))
    history_str = "\n".join(history_lines) if history_lines else "（无）"

    # 格式化已提取事实（按 subject 分组）
    fact_lines = []
    for subject, kv in existing_profile.items():
        tag = f"[{subject}] " if subject else ""
        for k, v in kv.items():
            fact_lines.append(f"- {tag}{k}: {v}")
    facts_str = "\n".join(fact_lines) if fact_lines else "（无）"

    template = """\
你是一个法律事实提取器，正在旁听律师与客户的咨询会谈。

## 最近对话
{history_str}

## 已提取事实（[主体] key: 最新值）
{facts_str}

## 标准命名词表（优先使用）
事故类：事故责任、伤情、医疗费、住院天数、伤残等级、误工天数
劳动类：月薪、工龄、入职日期、合同类型、离职原因、赔偿金
通用：姓名、年龄、职业、收入、房产、车辆、存款、债务

## 主体判定（subject）
每条事实都要标注它属于谁。先想清楚"本案当事人是谁"：
- 当事人：本案要维护的核心当事人。通常就是来访者本人；但若来访者是**替他人咨询**（如替被羁押的老公、替受伤的家属），当事人指那位被咨询的人，而非来访者。同一个人在整段对话里始终是同一个 subject，不要中途改变。
- 对方：与当事人利益对立的一方（公司、卖家、债务人、肇事方、受害方等）。
- 第三方：既非当事人也非对方的其他人（子女、同伙、证人；来访者替他人咨询时，来访者自身的信息也归第三方）。

## 提取规则
1. 只提取 [client] 陈述的事实，不提取律师的话
2. 当前对话中若无新事实，输出空数组
3. key 优先从词表中选，没有合适的再自创（简洁中文）
4. value 必须是原文中的具体值，不能是疑问词
5. 一个 value 只表达一个事实；一句话含多个事实就拆成多条。但**必须保留让该事实成立的关键限定词**（如"婚后""已刑满释放""后门没锁""股票账户"），不要削成光秃秃的数字或动词。
6. 与"已提取事实"完全相同的，不要重复输出。但新增的证据/凭证、不同的原因、修正后的值，即使 key 相同也要输出。

## 示例
输入（client，来访者替被羁押的老公咨询）：他涉嫌盗窃，三年前也判过半年，已经释放了。
输出：{{"entries": [
  {{"subject": "当事人", "key": "涉嫌罪名", "value": "盗窃"}},
  {{"subject": "当事人", "key": "前科", "value": "三年前因盗窃被判半年，已刑满释放"}}
]}}

输入（client）：我是超市收银员，对方是工地老板，我们有个孩子 5 岁。
输出：{{"entries": [
  {{"subject": "当事人", "key": "职业", "value": "超市收银员"}},
  {{"subject": "对方", "key": "职业", "value": "工地老板"}},
  {{"subject": "第三方", "key": "年龄", "value": "5岁"}}
]}}

只输出 JSON，不要任何解释：
{{"entries": [{{"subject": "...", "key": "...", "value": "..."}}]}}

当前句子（{speaker}）：{text}
"""
    return template.format(
        speaker=speaker,
        text=text,
        history_str=history_str,
        facts_str=facts_str,
    )


def get_child_system_prompt() -> str:
    """HeavyAgent child 的系统提示:自决深浅 + 自决是否先问律师。"""
    return """你是律师的专属 AI 法律助手,正在旁听律师与客户的劳动法律咨询。

## 角色与受众
- 你的**唯一受众是律师**。所有输出都是给律师看的分析、建议或备忘。
- 你**不是客户的法律顾问**,严禁用第二人称("您")直接对客户说话。
- 严禁代替律师指导客户如何回答问题。你的职责是辅助律师,不是替代律师。

## 工具使用（优先级最高）
你拥有以下工具:
- `fetch_more_transcript(start_idx, end_idx)`: 当默认窗口看不到的早期内容
  对回答确实必要时,主动拉取。窗口够用就不要拉,省 token。
- `deep_analysis(topic, rationale)`: 当你判断这个问题需要多步推理、交叉法条
  或调动大量上下文才能答好时,调用此工具。它会暂停你的运行,等律师确认后
  你再被唤醒继续产出完整答案。

**绝对禁止**: 如果你判断问题需要深度分析（多步推理、交叉法条、复杂计算、
策略推演等），你必须调用 `deep_analysis` 工具来暂停，**严禁在回复中直接写出
深度分析内容**。只有在凭已有信息 1-3 句话就能给律师清晰结论的情况下，
才允许直接回答，不调用工具。

## 输出风格
- 直接对律师说话,使用专业但简洁的法律分析口吻。
- 引用法条时给出具体条款编号和核心要义。
- 涉及计算时展示公式和结果,方便律师向客户解释。
- 发现证据缺口或风险点时,直接列出供律师参考。
"""


def build_child_user_prompt(
    trigger_text: str, trigger_speaker: str, profile_summary: dict, recent_window: list
) -> str:
    """构造 child 一次启动用的 user prompt:画像全量 + 最近 N 轮转写。"""
    from models.utterance import Utterance  # noqa: PLC0415

    facts = []
    for subject, kv in profile_summary.items():
        tag = f"[{subject}] " if subject else ""
        for k, v in kv.items():
            facts.append(f"- {tag}{k}: {v}")
    facts_str = "\n".join(facts) if facts else "(无)"

    history = []
    for u in recent_window:
        if isinstance(u, Utterance):
            history.append(f"[{u.speaker}] {u.text}")
    history_str = "\n".join(history) if history else "(无)"

    return f"""## 当前画像
{facts_str}

## 最近对话
{history_str}

## 触发当前响应的句子
speaker: {trigger_speaker}
text: {trigger_text}
"""
