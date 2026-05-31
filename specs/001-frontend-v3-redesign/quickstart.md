# Quickstart: 前端 V3 重构

**Date**: 2026-05-30
**Feature**: 前端 V3 重构

## 开发环境启动

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖（如未安装）
pnpm install

# 3. 启动开发服务器
pnpm dev
```

开发服务器默认在 `http://localhost:5173` 启动。

## 同时启动后端（提供 API 和 WebSocket）

```bash
# 在另一个终端
cd backend
uv run uvicorn main:app --reload
```

后端默认在 `http://localhost:8000` 启动，WebSocket 端点为 `ws://localhost:8000/ws/{sessionId}`。

## 查看设计稿

设计稿文件位于 `frontend/public/design-mockup-v3.html`，可直接在浏览器中打开查看视觉效果。

## shadcn/ui 组件管理

项目已集成 shadcn/ui（`base-nova` 风格）。新增基础组件时使用 CLI：

```bash
# 安装新组件（示例）
cd frontend
npx shadcn add tooltip
npx shadcn add separator
```

业务组件（如 `InsightCard`、`ProfilePanel`）应基于 `components/ui/` 中的基础组件组合扩展，不直接修改 `ui/` 目录内文件。

## 关键文件结构

```
frontend/src/
├── pages/
│   ├── EntryPage.tsx          # 入口页（新/重写）
│   └── LiveSession.tsx        # 实时会谈页（重写）
├── components/
│   ├── ui/                    # shadcn/ui 基础组件（由 CLI 管理）
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── badge.tsx
│   │   ├── scroll-area.tsx
│   │   └── collapsible.tsx
│   ├── layout/
│   │   ├── DesktopLayout.tsx  # 桌面三栏布局
│   │   └── MobileLayout.tsx   # 移动端单栏布局
│   ├── profile/
│   │   └── ProfilePanel.tsx   # 当事人画像展板
│   ├── insights/
│   │   ├── InsightStream.tsx  # 洞察流容器
│   │   ├── InsightCard.tsx    # 洞察卡片（法规引用/风险提示等）
│   │   └── SuggestionCard.tsx # 可分析意图卡片
│   └── transcript/
│       └── TranscriptPanel.tsx # 精简转写参考
├── hooks/
│   └── useWebSocket.ts        # 复用现有 hook
├── api/
│   └── sessions.ts            # 复用现有 API 调用
├── types/
│   └── index.ts               # 数据类型定义（从 data-model.md 同步）
└── App.tsx                    # 路由入口（调整）
```

## 测试

```bash
# 运行前端测试
pnpm test

# 运行类型检查
pnpm tsc --noEmit

# 代码检查
pnpm lint
```

## 部署构建

```bash
pnpm build
```

构建产物输出到 `frontend/dist/`。
