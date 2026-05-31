# Implementation Plan: 前端 V3 重构

**Branch**: `001-frontend-v3-redesign` | **Date**: 2026-05-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-frontend-v3-redesign/spec.md`

## Summary

重构法律 AI 辅助会谈系统的前端页面，以 `design-mockup-v3.html` 为视觉标准，实现入口页、桌面端实时会谈三栏布局、移动端单栏 Tab 布局。复用现有 WebSocket 和 HTTP API，不修改后端。

## Technical Context

**Language/Version**: TypeScript 5.x

**Primary Dependencies**: React 18, Vite, Tailwind CSS, shadcn/ui (`base-nova` 风格), Lucide React

**Storage**: N/A（纯前端，数据来自后端 API/WebSocket）

**Testing**: Vitest（通过 `pnpm test`）

**Target Platform**: Chrome/Edge/Safari（桌面端 1440×900+），移动端浏览器（390×844）

**Project Type**: web-application

**Performance Goals**: Tab 切换 <200ms，洞察卡片渲染 <500ms，入口页到会谈页 <3s

**Constraints**: 响应式断点 `md:`（768px）切换桌面/移动端，深色主题唯一，移动端强制竖屏

**Scale/Scope**: 3 个主要页面（入口页、桌面会谈页、移动会谈页），约 8-10 个组件

## Constitution Check

Constitution 文件为模板状态，无具体项目治理约束。默认遵循以下原则：
- 简单第一：不引入不必要的依赖
- 目标驱动执行：每个组件有明确的验收标准
- 遵从现有习惯：使用项目已有的 TypeScript/React/Tailwind 技术栈

*GATE: 通过。*

## Project Structure

### Documentation (this feature)

```text
specs/001-frontend-v3-redesign/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── websocket-messages.md
│   └── http-api.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
frontend/src/
├── pages/
│   ├── EntryPage.tsx          # 入口页（重写）
│   └── LiveSession.tsx        # 实时会谈页（重写，作为布局调度器）
├── components/
│   ├── ui/                    # shadcn/ui 基础组件（由 CLI 管理）
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── badge.tsx
│   │   ├── scroll-area.tsx
│   │   └── collapsible.tsx
│   ├── layout/
│   │   ├── DesktopLayout.tsx  # 桌面三栏布局
│   │   └── MobileLayout.tsx   # 移动端单栏布局 + Tab 导航
│   ├── profile/
│   │   └── ProfilePanel.tsx   # 当事人画像展板（5 个模块）
│   ├── insights/
│   │   ├── InsightStream.tsx  # 洞察流容器 + 空状态
│   │   ├── InsightCard.tsx    # 洞察卡片（4 种类型）
│   │   └── SuggestionCard.tsx # 可分析意图卡片（3 种状态）
│   └── transcript/
│       └── TranscriptPanel.tsx # 精简转写参考（可折叠）
├── hooks/
│   └── useWebSocket.ts        # 复用现有 hook
├── api/
│   └── sessions.ts            # 复用现有 API 调用
├── types/
│   └── index.ts               # 数据类型定义
├── context/
│   └── SessionContext.tsx     # 会话级状态管理
└── App.tsx                    # 路由调整
```

**Structure Decision**: 采用上述前端组件结构。现有 `useWebSocket.ts` 和 `sessions.ts` 复用不修改。新增 `SessionContext` 管理会话级状态（profile/insights/suggestions/transcripts），避免 prop drilling。`components/ui/` 为 shadcn/ui 基础组件目录，由 `npx shadcn add` 管理；业务组件（layout/profile/insights/transcript）基于 shadcn 组件组合扩展，不直接修改 `ui/` 内文件。

## Design Decisions

| 决策 | 选择 | 理由 |
|------|------|------|
| UI 组件库 | shadcn/ui（`base-nova` 风格） | 项目已有集成，优先复用并扩展其组件（Card、Button、Badge、ScrollArea 等），通过 Tailwind 覆盖匹配 design-mockup-v3 深色主题 |
| 状态管理 | React Context + useReducer | 状态范围明确，不引入全局 store |
| 响应式断点 | Tailwind `md:`（768px） | 与现有项目配置一致 |
| 颜色方案 | Tailwind 扩展 + CSS 变量 | 兼顾 className 便利和运行时扩展 |
| 图标 | Lucide React（shadcn 默认） | 与 shadcn/ui 集成一致，图标丰富且支持 `currentColor` |
| 后端集成 | 复用现有 API，不修改后端 | WebSocket 和 HTTP 接口已满足需求 |
