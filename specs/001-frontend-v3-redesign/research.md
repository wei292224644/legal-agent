# Phase 0 Research: 前端 V3 重构

**Date**: 2026-05-30
**Feature**: 前端 V3 重构
**Spec**: [spec.md](spec.md)

## 技术决策

### UI 组件策略

**Decision**: 积极使用项目已有的 shadcn/ui（`base-nova` 风格）构建组件，通过 Tailwind 自定义样式匹配 design-mockup-v3 深色主题。

**Rationale**:
- 项目已集成 shadcn/ui，已有组件：Button、Card、Badge、Collapsible、ScrollArea，可直接复用
- shadcn 组件基于 Radix UI，无头设计，样式层完全可控，可通过 Tailwind 覆盖为深色主题
- 避免从零手写基础交互组件（如按钮状态、滚动区域、折叠面板），减少重复劳动
- 新增组件应优先通过 `npx shadcn add` 安装再定制，而非完全手写

**Alternatives considered**:
- 纯手写：项目已有 shadcn，重复造轮子无意义
- Material UI / Ant Design：主题系统与 design-mockup 差异过大，覆盖成本高

### 状态管理方案

**Decision**: React Context + `useReducer` 管理会话级状态，局部状态用 `useState`。

**Rationale**:
- 状态范围明确：仅当前会话的 transcript、insights、suggestions、profile、connection status
- 不涉及跨会话共享状态，不需要全局 store
- 数据流简单：WebSocket 推送 → state 更新 → UI 渲染
- 避免引入 Zustand/Jotai/Redux 增加复杂度

### 响应式断点

**Decision**: 以 Tailwind `md:`（768px）作为桌面/移动端分界。

**Rationale**:
- 设计稿 Desktop 基准为 1440×900，Mobile 基准为 390×844
- `md:`（768px）以下使用移动端单栏布局，及以上使用桌面三栏布局
- 与现有项目 Tailwind 配置一致

### 颜色/主题实现

**Decision**: Tailwind config 扩展自定义颜色 + CSS 变量双重方案。

**Rationale**:
- 设计稿中同时使用了 Tailwind 的 `bg-bg-primary` 等自定义颜色和 CSS 变量 `var(--bg-primary)`
- Tailwind 扩展便于在 className 中使用，CSS 变量便于运行时动态调整（如未来主题切换预留）
- 优先使用 Tailwind className，CSS 变量作为辅助（如渐变、阴影中的颜色引用）

### 图标方案

**Decision**: Lucide React（shadcn/ui 默认图标库）。

**Rationale**:
- shadcn/ui 已集成 lucide，与组件生态一致
- 图标丰富（Mic、Activity、User、MessageSquare、Check 等），可直接匹配设计稿需求
- 支持 `currentColor` 继承父元素颜色，适配深色主题无额外工作
- 无需手动维护内联 SVG，减少组件体积噪音

## 集成分析

### 与现有后端的集成

**Decision**: 复用现有 WebSocket 和 HTTP API，不修改后端。

**Rationale**:
- 现有 `useWebSocket` hook 已提供 transcript、analysis、suggestion、confirm_ack 消息处理
- 现有 `fetchHistory` 已提供历史数据回填
- 新增需求（如转写面板折叠状态、移动端 Tab 切换）均为前端本地状态，无需后端变更

### 与现有前端代码的关系

**Decision**: 完全重写，直接替换旧文件。

**Rationale**:
- 已通过 `/speckit-clarify` 确认（Q1）
- 旧版 UI 与设计稿 v3 差异过大，修改成本高于重写
- 旧文件路径：主要是 `frontend/src/pages/LiveSession.tsx` 和入口页相关文件
