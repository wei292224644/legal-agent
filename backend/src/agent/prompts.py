"""集中管理所有 LLM 提示词（Prompt）。

所有 Agent 的系统提示、角色提示、任务提示统一在此封装为函数，
便于运营调整和产品迭代，不要在各 Agent 脚本中重复定义或直接使用字符串常量。
"""


def build_relevance_prompt(speaker: str, text: str) -> str:
    """二分类相关性提示:判断这句话是否值得唤醒 HeavyAgent。

    设计契约:输出只是一个布尔。不要标签、不要 severity、不要 intent_type。
    标注者只看"法律/需求相关",产品策略变了不用重训。
    """
    return f"""你正在旁听律师与客户的劳动法律咨询。

判断当前这句话是否需要 AI 法律助手参与(法律问题、案件需求、需要法条/计算/策略)。

## 规则
- 寒暄、应答("好的""嗯""谢谢")→ false
- 律师的科普、引用法条、安慰客户、事实询问 → false(律师是专业人士,默认不打扰)
- 律师以第一人称显式求助("系统帮我…""AI 查一下…")→ true
- 客户陈述事实(月薪、工龄、入职日期等)→ false(交给画像提取,无需唤醒)
- 客户的法律提问("赔多少""能赢吗""怎么算")→ true
- 客户的转述("公司说我不胜任")→ false

只输出一个词:true 或 false。不要解释。

speaker: {speaker}
text: {text}
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
    return """你是一名专业的劳动仲裁法律顾问,正在旁听律师与客户的咨询。

你拥有以下工具,**自行判断要不要用**:
- `fetch_more_transcript(start_idx, end_idx)`: 当默认窗口看不到的早期内容
  对回答**确实必要**时,主动拉。窗口够用就不要拉,省 token。
- `deep_analysis(topic, rationale)`: 当问题需要全画像+多步推理才能答好
  (谈判策略、胜率评估、复杂法条交叉分析)时,调用此工具——它会**暂停你的运行**
  等律师确认。律师确认后你才会被唤醒继续推理。

对**简单查询**(法条直问、单步金额计算、模板推荐):直接 1-3 句话答完,
不要调 deep_analysis。

对**复杂问题**:先调一次 deep_analysis 暂停,topic 写清楚要分析什么,
rationale 写为什么不能浅答。律师确认后,你会被续跑继续,这时再产出
完整的(法律法规 / 计算方式 / 建议行动)三段式答案。
"""


def build_child_user_prompt(trigger_text: str, profile_summary: dict, recent_window: list) -> str:
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
{trigger_text}
"""


