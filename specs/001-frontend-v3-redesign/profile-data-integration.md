# 当事人画像数据打通设计

**日期**: 2026-05-31 | **关联计划**: [plan.md](plan.md)

## 问题

前端 `ProfilePanel` 组件完整实现了 5 个模块 UI，但 `state.profile` 始终为 `null`，页面只显示骨架占位符。

**根因**：后端 `ProfileAgent` + `ContextStore` 已在收集画像数据（从当事人发言中提取法律事实 key-value），但从未通过 WebSocket 或 HTTP 推送给前端。

## 方案

扩展现有 WebSocket 协议，新增 `profile_update` 消息类型。后端在 profile worker 写入新条目后推送当前画像快照。HTTP history 接口同步补上 profile 数据用于页面刷新/重连恢复。

### 数据流

```
当事人发言 → ProfileAgent.extract() → ContextStore.enqueue_profile_update()
                                              ↓
                                       profile_worker 写 DB + 内存
                                              ↓
                                       回调通知 WS 推送 profile_update
                                              ↓
                                       前端 setProfile() → ProfilePanel 渲染
```

### 消息格式

```json
{
  "type": "profile_update",
  "entries": [
    { "key": "工伤时间", "value": "2024年3月", "subject": "当事人" },
    { "key": "月薪", "value": "约5000元", "subject": "当事人" },
    { "key": "公司名称", "value": "XX建筑公司", "subject": "对方" }
  ]
}
```

## 改动清单

### 后端

| 文件 | 改动 | 说明 |
|------|------|------|
| `main.py` | 在 `on_suggestion` 回调同层增加 profile 推送逻辑 | profile worker 每批写入后，读 `ctx.get_profile_summary()` 推给 WS |
| `main.py` | `/api/sessions/{id}/history` 补 `profile_entries` 字段 | 页面刷新/重连时恢复画像状态 |

不改 `orchestrator.py` 和 `context_store.py` —— 它们只负责生产数据，推送是 WS handler 层的职责。

### 前端

| 文件 | 改动 | 说明 |
|------|------|------|
| `useWebSocket.ts` | 增加 `onProfileUpdate` 回调 + 解析 `profile_update` 消息 | 遵循现有 onTranscript/onAnalysis/onSuggestion 模式 |
| `LiveSession.tsx` | 接收 profile 数据调 `setProfile` | 在 WebSocket callbacks 中新增 onProfileUpdate |
| `ProfilePanel.tsx` | 适配数据源 | 将 key-value 条目映射到已确认事实和关键主张模块 |

### ProfilePanel 模块映射（V1）

| 模块 | V1 实现 | 数据来源 |
|------|---------|----------|
| 基本信息 | 留空 | 需要额外 LLM 推断，V1 不做 |
| 情绪状态 | 留空 | 需要情感分析，V1 不做 |
| **关键主张** | 展示 `subject="当事人"` 且含争议性关键词的条目 | ProfileEntry 直接映射 |
| 风险暴露 | 留空 | 需要风险评估，V1 不做 |
| **已确认事实** | 展示所有 key-value 条目 | ProfileEntry 直接映射 |

留空的 3 个模块显示"分析进行中"提示，后续版本加 LLM 综合分析步骤填满。

## 验证标准

1. 当事人说话后，前端 ProfilePanel 的"已确认事实"模块实时出现新条目
2. 刷新页面后，画像数据通过 HTTP history 接口恢复，不丢失
3. 律师发言不触发画像更新
