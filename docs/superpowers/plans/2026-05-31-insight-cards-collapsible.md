# 实时洞察卡片折叠与摘要实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 深度分析 ready 态卡片默认折叠并显示 120 字摘要，快答 prompt 约束 200 字以内。

**Architecture:** 前端 `SuggestionCard.tsx` 的 `ReadyCard` 子组件在折叠态增加 `text` 前 120 字摘要预览；后端 `prompts.py` 在快答系统提示中追加字数约束。改动范围极小，无状态层影响。

**Tech Stack:** React + TypeScript + Tailwind（前端），Python 字符串（后端 prompt）

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `backend/src/agent/prompts.py` | HeavyAgent child 系统提示，追加快答 200 字约束 |
| `frontend/src/components/insights/SuggestionCard.tsx` | `ReadyCard` 折叠态增加正文摘要预览 |

---

### Task 1: 后端快答 prompt 增加 200 字约束

**Files:**
- Modify: `backend/src/agent/prompts.py:135-140`

- [ ] **Step 1: 修改 `get_child_system_prompt()`**

在 `# 快答格式` 段落后追加字数约束：

```python
# 快答格式
不要在你的快答回复中加"快答"标题或任何前缀,直接说出对律师有用的内容即可。
回答应简洁明了，控制在 200 字以内。
```

具体修改（`backend/src/agent/prompts.py` 第 135-137 行）：

```python
# 快答格式
不要在你的快答回复中加"快答"标题或任何前缀,直接说出对律师有用的内容即可。
回答应简洁明了，控制在 200 字以内。
```

- [ ] **Step 2: 运行后端测试确认无回归**

Run: `cd backend && uv run pytest -x -q`
Expected: 全部通过（当前 11 passed）

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/prompts.py
git commit -m "$(cat <<'EOF'
prompt: 快答系统提示增加 200 字约束

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 前端 ReadyCard 折叠态增加摘要预览

**Files:**
- Modify: `frontend/src/components/insights/SuggestionCard.tsx:108-146`

- [ ] **Step 1: 修改 `ReadyCard` 组件**

当前 `ReadyCard` 折叠态只显示 `topic` + 展开按钮。修改为同时显示 `text` 前 120 字摘要。

修改后的完整 `ReadyCard`：

```tsx
function ReadyCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false)

  const preview = suggestion.text
    ? suggestion.text.slice(0, 120) + (suggestion.text.length > 120 ? '...' : '')
    : ''

  return (
    <div className="mb-5 p-4 rounded-lg bg-bg-secondary border border-border-color">
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <CheckCircle2 className="w-3 h-3 text-success shrink-0" />
            <span className="text-xs font-medium text-success shrink-0">
              {suggestion.topic || '深度分析'}
            </span>
            {!expanded && preview && (
              <span className="text-xs text-ink-muted truncate">
                · {preview}
              </span>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs h-auto py-1 px-2 shrink-0 text-ink-secondary hover:text-ink-primary"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3 h-3" /> 收起
              </>
            ) : (
              <>
                <ChevronDown className="w-3 h-3" /> 展开
              </>
            )}
          </Button>
        </div>
        <CollapsibleContent>
          <div className="mt-3">
            <MarkdownText>{suggestion.text ?? '分析结果为空'}</MarkdownText>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
```

关键变更点：
1. 新增 `preview` 变量：`text` 前 120 字，超长加 `...`。
2. 折叠态标题行增加 `<span className="text-xs text-ink-muted truncate">· {preview}</span>`。
3. 标题行容器加 `min-w-0`，确保 `truncate` 生效。

- [ ] **Step 2: 运行前端测试确认无回归**

Run: `cd frontend && pnpm test`
Expected: 全部通过（当前 8 passed）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/insights/SuggestionCard.tsx
git commit -m "$(cat <<'EOF'
feat(insights): 深度分析 ready 态折叠时显示 120 字摘要

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

1. **Spec coverage:**
   - 深度分析 ready 态默认折叠 + 120 字摘要 → Task 2 ✅
   - 快答 prompt 200 字约束 → Task 1 ✅
   - pending / running 态不变 → 未触及相关代码 ✅
   - 快答不折叠 → 未触及 `InsightCard` ✅

2. **Placeholder scan:** 无 TBD/TODO/"fill in details"。

3. **Type consistency:** 未引入新类型，仅使用现有 `Suggestion.text`（`string | null`）。

---

**执行选项:**

1. **Subagent-Driven (recommended)** — 每个 Task 派一个子代理实现 + 两阶段审查
2. **Inline Execution** — 在当前会话直接执行

请选一种方式继续。
