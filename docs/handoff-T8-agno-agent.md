# Handoff: legal-agent — T8 Agno Agent

**日期:** 2026-05-26 | **分支:** main | **前置任务:** T7 音频管道

## 任务目标

实现 `backend/agent/` — Agno Agent 接收转写文本，调用 deepseek-v4-pro 实时分析，流式返回法规/合同/风险 JSON。

## 上下文

法律会谈实时 AI 辅助系统。T7 音频管道完成后，转写文本（带角色标签）通过 WebSocket 到达前端，同时送入 Agent 做实时法律分析。

### 上游依赖（T7 产出格式）

```json
{"type": "transcript", "text": "您这个情况属于...", "speaker": "律师", "is_final": true}
```

### 下游期望（Agent 产出 → 前端侧边栏）

```json
{
  "type": "analysis",
  "category": "statute",
  "title": "劳动合同法 第82条",
  "content": "用人单位自用工之日起超过一个月不满一年未订立书面劳动合同...",
  "citation": "《中华人民共和国劳动合同法》"
}
```

## 技术决策

| 决策 | 选择 |
|------|------|
| Agent 框架 | Agno（已安装 `agno>=2.6.0`）|
| LLM | deepseek-v4-pro（OpenAI 兼容 API）|
| Session 管理 | Agno `session_state` → `transcript_window`（最近10句）+ `legal_issues`（已识别问题摘要）|
| 存储 | Agno `SqliteDb` — session + memory 持久化 |
| Tools | 3 个 `@tool`：`statute_lookup`、`contract_template`、`risk_assess` |
| 输出 | 流式 JSON，deepseek-v4-pro 原生支持 streaming |

## 文件结构

```
backend/agent/
  __init__.py
  prompt.py      — System Prompt（中国执业律师 + JSON 输出约束）
  tools.py       — @tool 函数：statute_lookup, contract_template, risk_assess
  agent.py       — Agno Agent 初始化 + 流式调用
```

### prompt.py — System Prompt

```
你是一位经验丰富的中国执业律师兼法律顾问。你正在实时旁听一场律师与客户的咨询会谈。

任务：
1. 实时识别对话中涉及的法律问题
2. 即时提供相关法规引用（精确到条、款、项）
3. 提供合同条款建议和范本片段
4. 标注潜在法律风险

输出 JSON 格式（严格遵守，不要输出其他内容）：
{
  "statutes": [{"law": "", "article": "", "content": "", "relevance": ""}],
  "contract_clauses": [{"title": "", "text": "", "rationale": ""}],
  "risks": [{"level": "高/中/低", "description": "", "mitigation": ""}]
}

规则：
- 只引用中国大陆现行有效的法律法规
- 法规引用必须精确，不确定时标注"[需要核实]"
- 如无相关建议，对应字段返回空数组
```

### tools.py — 3 个 @tool Skill

```python
from agno.tools import tool

@tool
def statute_lookup(law_name: str, article: str = "") -> str:
    """查询中国法律法规条文。law_name 如'劳动合同法'，article 如'第82条'"""
    # Demo 阶段：返回预置的常用法规条文
    ...

@tool
def contract_template(contract_type: str, context: str) -> str:
    """根据对话上下文生成合同条款模板"""
    ...

@tool
def risk_assess(scenario: str, facts: list[str]) -> dict:
    """评估法律风险等级并给出应对建议"""
    ...
```

### agent.py — Agno Agent

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat  # deepseek 兼容 OpenAI API

from .prompt import SYSTEM_PROMPT
from .tools import statute_lookup, contract_template, risk_assess

def create_agent() -> Agent:
    return Agent(
        model=OpenAIChat(
            id="deepseek-v4-pro",
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        ),
        tools=[statute_lookup, contract_template, risk_assess],
        instructions=SYSTEM_PROMPT,
        db=SqliteDb(db_file="data/agent.db"),
        add_history_to_context=True,
        num_history_runs=5,
    )
```

## WebSocket 集成点（main.py 中调用）

```python
from agent.agent import create_agent

agent = create_agent()

# 在 legal_session WebSocket handler 中：
async for chunk in agent.stream_run(transcript_text):
    await ws.send_json(chunk)
```

## 测试要点

1. Agent 初始化 → 模型 + tools + prompt 配置正确
2. `statute_lookup("劳动合同法", "第82条")` → 返回条文内容
3. `contract_template("解除劳动合同协议", "未签合同")` → 返回模板
4. `risk_assess("未签劳动合同", ["入职3个月未签"])` → 返回风险等级+建议
5. Agent 完整调用：输入转写文本 → 返回有效 JSON（statutes/contract_clauses/risks）
6. LLM 返回非 JSON → 降级处理（返回空 analysis + error 标记）

## 环境变量

```bash
# backend/.env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

## 估时

human ~1h / CC ~20min

## 建议 Skills

1. `/tdd` — TDD 循环实现 Agent
2. `docs/design.md` — 完整设计文档
3. `docs/handoff-T7-audio-pipeline.md` — T7 交接文档（Agent 上游）
