# Tasks: 前端 V3 重构

**Input**: Design documents from `/specs/001-frontend-v3-redesign/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story this task belongs to (US1, US2, US3, US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Tailwind 主题配置、类型定义、路由准备

- [x] T001 在 `frontend/tailwind.config.ts` 中扩展 design-mockup-v3 自定义颜色（bg/ink/accent/success/danger/contract）
- [x] T002 在 `frontend/src/types/index.ts` 创建全局类型定义（Profile, Insight, Suggestion, TranscriptLine, Session）
- [x] T003 在 `frontend/src/App.tsx` 调整路由结构，支持入口页和会谈页路由

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 会话状态管理和 shadcn/ui 基础准备

**⚠️ CRITICAL**: 所有用户故事依赖此阶段完成

- [x] T004 在 `frontend/src/context/SessionContext.tsx` 实现会话级状态管理（React Context + useReducer，含 profile/insights/suggestions/transcripts/connectionStatus）
- [x] T005 [P] 确认 `frontend/src/components/ui/` 中 shadcn 基础组件可用（Button, Card, Badge, ScrollArea, Collapsible），必要时补充安装缺失组件
- [x] T006 [P] 在 `frontend/src/index.css` 中配置 CSS 变量和深色主题全局样式

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 — 律师在桌面端开展实时会谈 (Priority: P1) 🎯 MVP

**Goal**: 桌面端三栏布局（画像展板 | 洞察流 | 转写参考），所有核心组件可正常渲染

**Independent Test**: 在桌面端浏览器（1440×900）打开会谈页面，能看到左侧画像、中间洞察流、右侧转写，各区域滚动独立

### Implementation for User Story 1

- [x] T007 [P] [US1] 在 `frontend/src/components/profile/ProfilePanel.tsx` 实现当事人画像展板（5 个模块：基本信息、情绪状态、关键主张、风险暴露、已确认事实），空状态占位
- [x] T008 [P] [US1] 在 `frontend/src/components/insights/InsightCard.tsx` 实现洞察卡片（4 种类型：法规引用/风险提示/合同条款/行为分析），基于 shadcn Card
- [x] T009 [P] [US1] 在 `frontend/src/components/transcript/TranscriptPanel.tsx` 实现精简转写参考面板（按说话人区分，可折叠），基于 shadcn Collapsible
- [x] T010 [US1] 在 `frontend/src/components/insights/InsightStream.tsx` 实现洞察流容器（渲染 Insight[] + Suggestion[] 混合列表 + 空状态提示），基于 shadcn ScrollArea
- [x] T011 [US1] 在 `frontend/src/components/layout/DesktopLayout.tsx` 实现桌面三栏布局（左 260px 固定 | 中自适应 | 右 280px 可折叠）
- [x] T012 [US1] 在 `frontend/src/pages/LiveSession.tsx` 重写会谈页，作为布局调度器（响应式切换 DesktopLayout/MobileLayout）

**Checkpoint**: US1 完整可用 — 桌面端三栏布局正常渲染，各组件独立滚动

---

## Phase 4: User Story 2 — 律师在移动端开展实时会谈 (Priority: P1)

**Goal**: 移动端单栏布局 + 底部 Tab 导航，复用 US1 核心组件

**Independent Test**: 在移动端浏览器（390×844）打开会谈页面，默认展示洞察流，Tab 切换正常

### Implementation for User Story 2

- [x] T013 [P] [US2] 在 `frontend/src/components/layout/MobileLayout.tsx` 实现移动端单栏布局 + 底部 Tab 导航（洞察/画像/转写）
- [x] T014 [P] [US2] 在 `frontend/src/components/profile/ProfilePanel.tsx` 添加移动端摘要模式（顶部折叠卡片）
- [x] T015 [US2] 在 `frontend/src/pages/LiveSession.tsx` 集成移动端强制竖屏检测和提示（使用 screen.orientation API + 横屏时全屏遮罩提示旋转设备）

**Checkpoint**: US2 完整可用 — 移动端布局正常，Tab 切换响应 <200ms

---

## Phase 5: User Story 3 — 律师在开始会谈前进入入口页 (Priority: P2)

**Goal**: 入口页展示产品介绍、开始新会谈按钮、声纹注册引导

**Independent Test**: 访问首页能看到产品介绍和「开始新会谈」按钮，点击后创建会话并跳转

### Implementation for User Story 3

- [x] T016 [P] [US3] 在 `frontend/src/pages/EntryPage.tsx` 实现入口页（左侧产品介绍文案 + 右侧操作区），匹配 design-mockup-v3 入口页设计
- [x] T017 [US3] 在 `frontend/src/pages/EntryPage.tsx` 实现「开始新会谈」按钮逻辑（调用 API 创建会话并跳转至 `/session/{id}`）

**Checkpoint**: US3 完整可用 — 入口页可独立访问，按钮跳转正常

---

## Phase 6: User Story 4 — 律师实时接收并处理分析建议 (Priority: P2)

**Goal**: 可分析意图卡片完整状态流转（pending → running → ready/dismissed）

**Independent Test**: 会谈中看到待分析意图卡片，点击「生成深度分析」后进入运行状态，完成后展示结果

### Implementation for User Story 4

- [x] T018 [P] [US4] 在 `frontend/src/components/insights/SuggestionCard.tsx` 实现可分析意图卡片（3 种状态：pending/running/ready，含进度指示）
- [x] T019 [P] [US4] 在 `frontend/src/hooks/useWebSocket.ts` 中集成 suggestion 消息处理到 SessionContext（复用现有 hook，无需修改后端）
- [x] T020 [US4] 在 `frontend/src/components/insights/SuggestionCard.tsx` 实现 confirm/dismiss 操作，调用 WebSocket send

**Checkpoint**: US4 完整可用 — 意图卡片状态流转正常，confirm/dismiss 生效

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 边缘情况、连接状态、性能优化、代码质量

- [x] T021 [P] 在 `frontend/src/pages/LiveSession.tsx` 实现网络断线自动重连和历史数据补全逻辑
- [x] T022 [P] 实现所有空状态和 loading 状态：画像展板 5 模块占位、洞察流空提示（含 Suggestion 空状态）、转写等待提示、EntryPage 加载态
- [x] T023 [P] 在 `frontend/src/components/layout/` 中实现连接状态指示器（在线/离线/重连中）
- [x] T024 运行 `pnpm tsc --noEmit` 和 `pnpm lint` 确保类型检查和代码检查全部通过
- [x] T025 运行 `pnpm test` 确保现有测试通过（不引入新测试，除非用户明确要求 TDD）
- [x] T026 在桌面端（1440×900）和移动端（390×844）验证所有 success criteria

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，可立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1 完成 — 阻塞所有用户故事
- **User Stories (Phase 3-6)**: 均依赖 Phase 2 完成
  - US1 和 US3 可在 Phase 2 后并行开发（无相互依赖）
  - US2 依赖 US1 的核心组件（ProfilePanel, InsightStream, TranscriptPanel）
  - US4 依赖 US1 的 InsightStream 和基础布局
- **Polish (Phase 7)**: 依赖所有用户故事完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 完成后即可开始，无其他故事依赖
- **US2 (P1)**: 依赖 US1 的核心组件完成（可复用 ProfilePanel, InsightStream, TranscriptPanel）
- **US3 (P2)**: Phase 2 完成后即可开始，完全独立
- **US4 (P2)**: 依赖 US1 的 InsightStream 完成

### Within Each User Story

- US1: T007/T008/T009 可并行 → T010 依赖 T008 → T011 依赖 T007/T009/T010 → T012 依赖 T011
- US2: T013/T014 可并行 → T015 依赖 T013
- US3: T016/T017 串行
- US4: T018/T019 可并行 → T020 依赖 T018/T019

### Parallel Opportunities

- Phase 1 中 T001/T002/T003 可并行
- Phase 2 中 T005/T006 可并行
- Phase 3 中 T007/T008/T009 可并行
- Phase 5（US3）可与 Phase 3-4（US1-US2）并行开发

---

## Parallel Example: Phase 3 (US1)

```bash
# 并行开发桌面端三个核心面板
Task: "T007 [US1] ProfilePanel in frontend/src/components/profile/ProfilePanel.tsx"
Task: "T008 [US1] InsightCard in frontend/src/components/insights/InsightCard.tsx"
Task: "T009 [US1] TranscriptPanel in frontend/src/components/transcript/TranscriptPanel.tsx"
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational
3. 完成 Phase 3: US1（桌面端三栏布局）
4. **STOP and VALIDATE**: 在桌面端测试三栏布局
5. 部署/demo

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → 桌面端会谈可用 → 部署/Demo（MVP!）
3. US2 → 移动端适配 → 部署/Demo
4. US3 → 入口页 → 部署/Demo
5. US4 → 分析建议完整体验 → 部署/Demo
6. Phase 7: Polish

### Parallel Team Strategy

多人协作时：

1. 团队共同完成 Phase 1 + Phase 2
2. Phase 2 完成后：
   - 开发者 A: US1（桌面端布局）
   - 开发者 B: US3（入口页，独立）
3. US1 完成后：
   - 开发者 A: US4（SuggestionCard 状态流转）
   - 开发者 B: US2（移动端布局，复用 US1 组件）
4. 最后共同完成 Phase 7: Polish

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- 每个用户故事应独立可完成、独立可测试
- 优先复用现有 `useWebSocket.ts` 和 `sessions.ts`，不修改后端
- shadcn/ui 组件通过 `npx shadcn add` 安装，不直接修改 `components/ui/` 内文件
- 所有组件基于 design-mockup-v3.html 的深色主题视觉标准实现
