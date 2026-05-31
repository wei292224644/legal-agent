# CLAUDE.md — legal-agent

---

## 🧭 项目概况

- **项目类型:** Web 应用 — 实时法律会谈 AI 辅助系统
- **主要语言:** Python (后端) + TypeScript (前端)
- **构建/运行:**
  - 后端安装: `cd backend && uv sync`
  - 前端安装: `cd frontend && pnpm install`
  - 环境配置: `cp backend/.env.example backend/.env`（填入实际 API Key）
  - 后端启动: `cd backend && uv run uvicorn main:app --reload`
  - 前端启动: `cd frontend && pnpm dev`
  - 后端测试: `cd backend && uv run pytest`
  - 后端测试(仅慢速): `cd backend && uv run pytest -m slow`
  - 后端代码检查: `cd backend && uv run ruff check .`
  - 后端格式化: `cd backend && uv run ruff format .`
  - 前端测试: `cd frontend && pnpm test`
  - 格式化/检查: `cd frontend && pnpm lint`
- **目录结构:**
  - `backend/` — Python FastAPI 后端（Agent 服务、音频管道、WebSocket）
    - `src/agent/` — Agent 核心：IntentRouter、ProfileAgent、HeavyAgent、Orchestrator、技能集
    - `src/session/` — 会话管理：SessionManager、SQLite 持久化、序列化、AI 摘要生成
    - `src/diarization/` — 说话人分离：声纹注册、匹配、voiceprint 工具
    - `src/stt/` — 语音转文字：FunASR 流式处理
    - `src/models/` — Pydantic 数据模型
    - `tests/` — 单元测试 + e2e 测试 + fixtures + 测试报告生成
  - `frontend/` — Vite + React 前端（声纹注册、实时会谈页）
    - `src/` — 页面组件、hooks、工具函数
  - `.gstack/` — gstack 设计文档和审查产物（不入 git）
- **命名约定:**
  - Python: snake_case 文件 + 函数
  - TypeScript: PascalCase 组件, camelCase 函数/hooks
- **外部依赖:**
  - **STT / 声纹（本地）:** FunASR — `fsmn-vad` 切句 + `paraformer-zh` 转写；`cam++`(campplus) 说话人声纹
  - **LLM:** 千问 (Qwen, DashScope OpenAI 兼容端点) — IntentRouter / ProfileAgent；DeepSeek (`deepseek-chat`，经 Agno) — HeavyAgent
  - **框架:** Agno (Agent)、instructor (结构化输出)、FastAPI、openai SDK
  - **设计 spec:** `backend/docs/superpowers/specs/*.md`

---

## 🤖 AI 行为准则

### 1. 想清楚再写

不要假设，不要隐藏困惑，暴露取舍。

- 实现之前先说出你的理解。不确定就先问。
- 如果需求有歧义，把几种理解都列出来，不要偷偷选一个。
- 如果有更简单的做法，说出来。
- 遇到不明白的地方，停下来，说清楚哪里卡住了。

### 2. 简单第一

能解决问题的代码就是好代码，不多写一行。

- 不要加需求以外的功能。
- 不要为只出现一次的场景做抽象或封装。
- 不要预留"以后可能用到"的灵活性或配置。
- 不要处理不可能发生的错误。
- 如果写了 200 行但 50 行就能搞定，重写。

问自己一句：「一个资深工程师会觉得这写复杂了吗？」如果答案是「会」，简化它。

### 3. 外科手术式改动

只碰你必须碰的。清理也只清理自己留下的。

改动已有代码时：
- 不要顺手"改良"旁边的代码、注释或排版。
- 不要重构没坏的东西。
- 保持与当前代码风格一致，哪怕你自己更喜欢另一种写法。
- 看到无关的废弃代码可以提一句，但不要删除它。

你的改动产生了废弃引用：清理你自己引入的未用 import / 变量 / 函数。不要删本就存在的废弃代码，除非被要求。

**判断标准：每一行改动都应该能直接追溯到需求。**

### 4. 目标驱动执行

先定义「完成」的标准，再动手。循环验证直到通过。

把模糊需求翻译成可验证的目标：

- "加个校验" → "针对非法输入写测试 → 让它通过"
- "修这个 bug" → "写一个能复现它的测试 → 让它通过"
- "重构模块 X" → "确保测试在重构前后都通过"

多步骤任务先简要陈述计划：

```
1. [步骤] → 验证: [检查项]
2. [步骤] → 验证: [检查项]
3. [步骤] → 验证: [检查项]
```

好的成功标准能让你独立完成循环。模糊的标准（"跑起来就行"）会需要不断确认。

---

### 5. 用模型做判断，不包办机械操作

LLM 适合做的事：分类、起草文案、总结、从非结构化文本中提取信息。

不适合硬套 LLM 的：路由分支、重试逻辑、状态码处理、可穷举的机械变换。

**原则：判断型任务用 LLM，确定型任务用纯代码。如果一个 if-else 就能回答的问题，用代码回答它。**

### 6. 关注成本，别硬撑

如果一个任务太长，写到一半上下文明显臃肿了——停下来，总结已完成的部分，换一个新对话继续。

**原则：意识到超载时说一声，比闷头写到出错要好。**

### 7. 暴露冲突，别搞折中

如果代码库里两种写法有矛盾，不要混在一起。

选一个（更新的 / 更可靠的），说明为什么选它，把另一个标记为待清理。

**"两者兼顾"的代码通常是最糟糕的代码。**

### 8. 先读再写

在文件里加代码之前，先看看这文件输出了什么、调用方是谁、以及相关的公共工具函数。

如果你搞不懂现有代码为什么这么写，先问，再加。

**"看起来跟我要加的东西是正交的"——这句话是项目里最危险的话。**

### 9. 测试验证意图，不只是行为

每个测试都要体现「为什么要测这个」，不只是「它测了什么」。

如果一个函数用了硬编码 ID，那 `expect(getUserName()).toBe('John')` 就是个废测试。

如果你写不出一个"业务逻辑变了就会挂"的测试，那你的函数设计有问题。

### 10. 每完成一步做一个检查点

多步骤任务的每一步做完之后：总结做了什么、验证了什么、还剩什么。

说不清当前状态就不要继续往下做。如果搞不清楚了，停下来，重新梳理。

### 11. 遵从项目现有的习惯，哪怕你不认同

项目用 snake_case 而你喜欢 camelCase？用 snake_case。

项目用类组件而你喜欢 hooks？用类组件。

**不认同可以另外开话题讨论，但在代码里，遵从大于个人品味。**

如果你确实认为某个约定有问题，把它提出来讨论，不要悄悄大改。

### 12. 失败时大声说出来

不确定某件事是否做对了，直说。

- "迁移完成"但默默跳过了 30 条记录——错误。
- "测试通过"但跳过了某些用例——错误。
- "功能能用"但没验证你提的那个边界情况——错误。

**宁可说出不确定性，不要掩盖它。**

---

## ⛔ 通用禁区

- 不要修改 `.git/`、`node_modules/`、`__pycache__/`、`build/`、`dist/` 等自动生成目录
- 不要直接修改或提交密钥、密码、环境变量中的敏感信息
- 不要修改第三方库（`site-packages/`、`node_modules/` 等）中的源码；如需 patch，通过 monkey-patch 或 vendoring 并在项目中管理
- 遇到需要 `sudo` 或高风险权限的操作，先停一下，问清楚再做
- 不要删除从未要求你修改过的既有代码

---

## 📦 文件编辑守则

- 大改动前先看完整文件，理解上下文
- 一次只做一个逻辑变更，不要混入无关修改
- 改完后跑相关测试，确保没破坏现有功能
- 如果改了多个文件，结束时列出改动清单

---

## Skill routing

**执行任何操作前（包括写代码、调试、审查、规划），先检查是否有 skill 可以规范并指导该操作。** 只有当 skill 与当前任务高度相关时才加载；禁止无差别、批量或预防性地加载所有 skill。

当用户请求与可用 skill 匹配时，通过 Skill 工具调用它。Skill 包含多步骤工作流、检查清单和质量门控，比即兴回答效果更好。不确定时，调用 skill；误报的代价比漏报更低。

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke /office-hours
- Strategy, scope, "think bigger", "what should we build" → invoke /plan-ceo-review
- Architecture, "does this design make sense" → invoke /plan-eng-review
- Design system, brand, "how should this look" → invoke /design-consultation
- Design review of a plan → invoke /plan-design-review
- Developer experience of a plan → invoke /plan-devex-review
- "Review everything", full review pipeline → invoke /autoplan
- Bugs, errors, "why is this broken", "wtf", "this doesn't work" → invoke /investigate
- Test the site, find bugs, "does this work" → invoke /qa (or /qa-only for report only)
- Code review, check the diff, "look at my changes" → invoke /review
- Visual polish, design audit, "this looks off" → invoke /design-review
- Developer experience audit, try onboarding → invoke /devex-review
- Ship, deploy, create a PR, "send it" → invoke /ship
- Merge + deploy + verify → invoke /land-and-deploy
- Configure deployment → invoke /setup-deploy
- Post-deploy monitoring → invoke /canary
- Update docs after shipping → invoke /document-release
- Weekly retro, "how'd we do" → invoke /retro
- Second opinion, codex review → invoke /codex
- Safety mode, careful mode, lock it down → invoke /careful or /guard
- Restrict edits to a directory → invoke /freeze or /unfreeze
- Upgrade gstack → invoke /gstack-upgrade
- Save progress, "save my work" → invoke /context-save
- Resume, restore, "where was I" → invoke /context-restore
- Security audit, OWASP, "is this secure" → invoke /cso
- Launch real browser for QA → invoke /open-gstack-browser
- Import cookies for authenticated testing → invoke /setup-browser-cookies
- Performance regression, page speed, benchmarks → invoke /benchmark
- Review what gstack has learned → invoke /learn
- Tune question sensitivity → invoke /plan-tune
- Code quality dashboard → invoke /health

---

## ⚠️ 项目特有模式

### Import 方式
`main.py` 位于项目根目录，通过 `sys.path.insert(0, str(Path(__file__).parent / "src"))` 引用本地模块，而非通过 `pip install -e .` 以包形式安装。修改 `main.py` 中的 import 时需保持此模式，避免 CI/生产环境路径问题。

### 声纹 Enrollment 单例
律师声纹在进程启动时通过 `_get_lawyer_enrollment()` 加载一次（基于 `tests/fixtures/律师声纹注册.wav`），后续每个 WebSocket 会话通过 `copy.deepcopy()` 获得独立副本，避免会话间的 client_embedding 污染。

### Session 恢复机制
`SessionManager` 在启动时从 SQLite 恢复未过期的会话状态。WebSocket 连接建立时，若 `session_id` 对应的状态已存在，则直接续接；若不存在但数据库有快照，则自动恢复。会话每 60 秒自动快照，TTL 600 秒。

<!-- SPECKIT START -->
当前 feature 计划: [specs/001-frontend-v3-redesign/plan.md](specs/001-frontend-v3-redesign/plan.md)
<!-- SPECKIT END -->
