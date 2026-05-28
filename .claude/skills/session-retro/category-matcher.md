# 分类匹配器（Category Matcher）

> 在归档阶段按需加载，用于确定每条教训应归入哪个 `sr-*` 分类 skill。

## 匹配算法

```
对每条确认的行动项：
  1. 提取 {根因} + {场景} 作为匹配键
  2. 列出 .claude/skills/ 下所有已有 sr-* skill
  3. 对每个已有 skill，读取其 SKILL.md
  4. 计算匹配键与 skill 内容的语义重叠度
  5. 最佳匹配分数 ≥ 阈值 → 追加到该 skill
  6. 最佳匹配分数 < 阈值 → 创建新 sr-* skill
```

## 语义相似度（规则代理）

在不具备精确向量计算时，使用规则代理：

### 第一步：关键词重叠

从根因和场景中提取**领域**，映射到常见分类：

| 根因领域 | 可能的分类 |
|---------|-----------|
| 命令执行、CWD、Shell、并行命令、验证顺序 | `cmd-conventions` |
| 架构、微服务边界、通信方式、服务隔离 | `arch-decisions` |
| 测试、Mock、断言、测试层级、RED-GREEN | `testing-patterns` |
| 执行流程、plan vs 实现、agent 调度、skill 调用 | `execution-decisions` |
| 代码风格、文件结构、命名、import 模式 | `code-conventions` |
| 用户沟通、何时问 vs 何时做、进度汇报 | `communication-patterns` |

### 第二步：读取已有 Skill

对最佳匹配的已有 skill，读取其 SKILL.md，检查：
- 新条目的根因是否与已有条目的根因重叠？
- 新条目的场景是否与已有条目的反例匹配？
- 如果任意匹配，这是**合并**（更新已有条目），而非新增条目

### 第三步：阈值决策

| 情况 | 操作 |
|------|------|
| 领域匹配已有 skill 且根因是新的 | 追加新条目 |
| 领域匹配且根因与已有条目重叠 | 合并/更新已有条目 |
| 领域是全新的（无已有 skill 匹配） | 创建新 `sr-{领域}` skill |
| 不确定属于哪个分类 | 在 AskUserQuestion 中列出两个选项 |

## 分类名推断

创建新分类 skill 时，从根因推断名称：

1. 从根因中提取**领域名词短语**
2. 转小写、连字符分隔
3. 前缀 `sr-`

示例：
- "并行 Bash 调用前无 CWD 检查" → 领域：命令规范 → `sr-cmd-conventions`
- "同步 HTTP 调用链超过 2 跳" → 领域：架构决策 → `sr-arch-decisions`
- "测试断言了实现细节而非行为" → 领域：测试模式 → `sr-testing-patterns`

## 新 Skill 模板

创建新的 `sr-*` skill 时，使用最小 frontmatter 和结构：

```markdown
---
name: session-retro:{分类}
description: 当 {根因领域衍生的触发条件} 时使用
---

# {分类标题}

由 session-retro 归档的教训。条目按时间倒序排列。

## 条目

### {第一条目标题}

**总结**：……

**反例**：……

**正确做法**：……
```
