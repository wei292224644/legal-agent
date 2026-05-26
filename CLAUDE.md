# CLAUDE.md — legal-agent

## 项目概况

- **项目类型:** {Web 应用 / CLI 工具 / 库}
- **主要语言:** {TypeScript / Python / Go / ...}
- **构建/运行:**
  - 启动: `{命令}`
  - 测试: `{命令}`
- **目录结构:** {描述关键目录的用途}

## AI 行为准则

1. 实现之前先说出你的理解，不确定就先问
2. 能解决问题的代码就是好代码，不多写一行
3. 只碰你必须碰的，不要顺手"改良"旁边的代码
4. 先定义"完成"的标准，再动手
5. 判断型任务用 LLM，确定型任务用纯代码
6. 如果任务太长，停下来总结，换新对话继续
7. 代码库里两种写法有矛盾，选一个，别折中
8. 先读再写
9. 测试验证意图，不只是行为
10. 每完成一步做一个检查点
11. 遵从项目现有的习惯，哪怕你不认同
12. 失败时大声说出来

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. The
skill has multi-step workflows, checklists, and quality gates that produce better
results than an ad-hoc answer. When in doubt, invoke the skill. A false positive is
cheaper than a false negative.

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
