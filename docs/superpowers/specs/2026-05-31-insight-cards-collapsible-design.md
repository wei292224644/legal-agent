# 实时洞察卡片折叠与摘要设计

> **目标:** 解决深度分析卡片内容过长占空间、以及折叠后无法预览内容的问题；同时通过 prompt 约束控制快答长度。

---

## 背景

当前实时洞察面板存在两个问题：
1. **深度分析（`Suggestion` ready 态）内容很长**，占用大量垂直空间。
2. **深度分析折叠后只显示 `topic`**，如果 `topic` 是泛泛的"深度分析"，用户完全不知道卡片里是什么内容。
3. **快答（`Insight`）有时也会偏长**，多条堆叠后同样占空间。

## 方案概述

采用"分层处理"策略：
- **快答**：保持直接展开，通过后端 prompt 约束字数（≤ 200 字），确保前端始终简短。
- **深度分析 ready 态**：默认折叠，折叠态显示 `topic` + 正文前 120 字摘要，展开显示完整内容。
- **pending / running 态**：保持现有交互样式不变（需要按钮/进度条空间）。

---

## 前端改动

### 1. `InsightCard` — 快答卡片（无改动）

保持当前直接展开的样式，不添加折叠交互。

依赖后端 prompt 约束确保长度。

### 2. `SuggestionCard` → `ReadyCard` — 深度分析 ready 态

折叠态增加正文摘要预览：

```tsx
function ReadyCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false)

  // 取 text 前 120 字作为摘要，超出加 "..."
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
          <Button ...>展开 / 收起</Button>
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

**设计细节：**
- 摘要取 `text` 纯文本前 120 字（Markdown 语法符号会一并计入，但 120 字足够短，影响可忽略）。
- 折叠态摘要用 `text-ink-muted` 灰色，前面加 `·` 分隔符，与 `topic` 区分开。
- 摘要使用 `truncate` 防止超长时破坏布局。
- `pending` 和 `running` 子组件完全不动。

---

## 后端改动

### `ProfileAgent` / 快答生成 prompt 增加字数约束

在生成快答（`insight.ready`）的 prompt 中追加约束：

```
...回答应简洁明了，控制在 200 字以内。
```

具体文件待确认（可能是 `backend/src/agent/profile_agent.py` 或 `backend/src/agent/orchestrator.py` 中调用 LLM 生成快答的位置）。

---

## 验收标准

- [ ] 深度分析 ready 态默认折叠，折叠态显示 topic + 120 字摘要。
- [ ] 展开后显示完整 Markdown 内容。
- [ ] pending / running 态样式不变。
- [ ] 快答卡片保持直接展开，不折叠。
- [ ] 后端快答 prompt 增加 "200 字以内" 约束。
- [ ] 前端测试通过。
