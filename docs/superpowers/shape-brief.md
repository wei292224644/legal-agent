# Shape Brief: LiveSession 响应式重设计

## 1. Feature Summary
重新设计 LiveSession 实时会谈页面，支持桌面端（会议室大屏）和移动端（外出手机）。律师在会谈中通过音频输入获得实时转写和 AI 分析。转写是后台记录，律师主要关注**系统状态和 AI 分析结果**，界面必须专业、冷静、反 AI 味。

## 2. Primary User Action
律师在会谈中能够**随时一瞥获取系统运行状态和 AI 风险提示**，无需持续关注屏幕，转写内容按需查看。

## 3. Design Direction
- **Color**: Restrained（已在 DESIGN.md 定义）
- **Theme**: 律师在会议室或法庭中，灯光偏暗，屏幕不应成为光源刺激。界面是 peripheral vision 中的可信参考，不是焦点。
- **References**: Linear（工具感与效率）、Things 3（专注与克制）、Bloomberg Terminal（信息密度与专业感）

## 4. Scope
- **Fidelity**: production-ready
- **Breadth**: LiveSession 主屏幕 + 响应式适配
- **Interactivity**: shipped-quality React components
- **Time intent**: 可立即投入使用

## 5. Layout Strategy

**Desktop (>1024px)**
- 左侧 35%：AI 分析面板（主导视觉，律师一瞥即见风险提示）
- 右侧 55%：转写区（可折叠/收起，默认显示最近 3 条，点击展开全部）
- 顶部 header：页面标题 + 系统状态 + 音频控制
- 底部：固定音频控制条（始终可见）

**Mobile (<768px)**
- 单面板，底部固定音频控制栏（始终可见）
- Tab 切换："分析"（默认）/ "转写"
- 分析面板全屏，转写面板可收起为底部小条
- 录音状态用顶部细条 + 脉冲指示

**信息层级**
1. AI 分析结果（最大面积，律师关注的核心价值）
2. 系统状态（录音中/已连接，一眼可见）
3. 转写内容（按需查看，不占主导）

## 6. Key States

| 状态 | 用户感知 |
|------|----------|
| 未连接 | 顶部状态条黄色，提示"连接中..." |
| 已连接 | 顶部状态条绿色，等待录音 |
| 录音中 | 红色脉冲 + "录音中"标签 |
| 播放中 | 播放进度条，可停止 |
| 分析中 | 分析卡片 placeholder 闪烁 |
| 空状态 | 优雅提示"开始说话，AI 将实时分析..." |
| 错误 | 顶部 toast，3 秒自动消失 |

## 7. Interaction Model
- **录音**：点击 → 请求权限 → 红色脉冲 → 点击停止
- **上传**：点击 → 选择文件 → 播放 + 进度条 → 完成/停止
- **移动端切换**：底部 Tab 切换分析/转写
- **AI 建议**：卡片底部"确认分析"/"忽略"按钮
- **转写区**：默认收起显示最近 3 条，点击展开全部，再次点击收起

## 8. Content Requirements
- 转写文本、说话人标签（律师/当事人）、时间戳
- AI 分析卡片：法规引用、合同条款、风险提示
- 状态文案："已连接"、"录音中"、"播放中"、"连接中..."
- 错误文案：权限拒绝、文件过大、格式不支持
- 空状态文案

## 9. Recommended References
- `reference/spatial-design.md` — 响应式布局策略
- `reference/interaction-design.md` — 状态转换和反馈
- `reference/motion-design.md` — 录音脉冲、进度动画

## 10. Open Questions
- 移动端分析面板是 Tab 切换还是底部 sheet 上滑？（当前设计为 Tab）
- 是否需要暗黑/亮色主题切换，还是纯暗黑？（当前设计纯暗黑）
