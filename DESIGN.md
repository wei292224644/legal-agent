# Design System

## Theme

Dark mode only. "律师在会议室或法庭中，灯光通常偏暗，屏幕不应成为光源刺激。深夜复盘录音时，深色界面更耐久。"

## Color Strategy: Restrained

Tinted neutrals + one amber accent ≤10%.

| Token | Value | Usage |
|-------|-------|-------|
| `bg-primary` | `#0d0b08` | 页面背景（向 amber 倾斜的极深暖灰） |
| `bg-secondary` | `#17140f` | 面板、卡片 |
| `bg-tertiary` | `#1e1b15` | 悬浮态、输入框 |
| `border-default` | `rgba(255,255,255,0.08)` | 分隔线、边框 |
| `border-hover` | `rgba(255,255,255,0.15)` | 悬浮边框 |
| `text-primary` | `#e5e5e5` | 主文本 |
| `text-secondary` | `#8a8a8a` | 次要文本、时间戳 |
| `text-muted` | `#525252` | 禁用、占位符 |
| `accent` | `#d4a853` | 律师标识、录音按钮、法规引用 |
| `accent-hover` | `#e0b86a` | accent 悬浮 |
| `accent-muted` | `rgba(212,168,83,0.15)` | accent 背景 tint |
| `risk-high` | `#c45c5c` | 高风险提示 |
| `risk-medium` | `#d4a853` | 中风险提示 |
| `risk-low` | `#6b8f6b` | 低风险提示 |
| `contract` | `#6b8ec4` | 合同条款标识 |
| `status-recording` | `#c45c5c` | 录音中脉冲 |
| `status-connected` | `#6b8f6b` | WebSocket 已连接 |

## Typography

| Role | Font | Size | Weight | Line-height |
|------|------|------|--------|-------------|
| Page title | Geist Sans | 20px | 500 | 1.3 |
| Section title | Geist Sans | 16px | 500 | 1.3 |
| Card title | Geist Sans | 14px | 500 | 1.4 |
| Body | Geist Sans | 14px | 400 | 1.6 |
| Small | Geist Sans | 12px | 400 | 1.5 |
| Mono label | Geist Mono | 11px | 400 | 1.4 | uppercase, tracking-wide |
| Speaker tag | Geist Mono | 11px | 500 | 1.2 |

## Spacing Scale

Base 4px. Scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

## Elevation

No drop shadows. Use 1px solid borders with `border-default` for elevation. Cards: `bg-secondary` + `border-default`.

## Border Radius

- Buttons: 6px
- Cards: 8px
- Tags/Badges: 4px
- Inputs: 6px

## Motion

- `prefers-reduced-motion` respected
- Default easing: `cubic-bezier(0.25, 0.1, 0.25, 1)` (ease-out-quart)
- Durations: 150ms (micro), 200ms (standard), 300ms (emphasis)
- No bounce, no elastic
- Recording pulse: opacity animation only, not scale

## Layout

### Desktop (>1024px)
- Two-pane layout: conversation (left, ~60%), analysis sidebar (right, ~40%)
- Max content width: 1400px, centered

### Tablet (768-1024px)
- Two-pane layout maintained, proportions adjust
- Analysis sidebar collapses to 35%

### Mobile (<768px)
- Single pane, tab switcher: "会谈" / "分析"
- Bottom fixed control bar for audio controls
- Full-width cards, no sidebar

## Components

### Button
- Primary: `bg-accent` `text-bg-primary` hover `bg-accent-hover`
- Secondary: `bg-transparent` `border-border-default` `text-primary` hover `bg-tertiary`
- Destructive: `bg-risk-high/20` `text-risk-high` hover `bg-risk-high/30`
- Height: 36px (standard), 32px (small)
- Padding: 0 16px

### Card
- `bg-secondary` + `border-default` + `rounded-lg` (8px)
- Padding: 16px
- No shadow

### Badge/Tag
- `bg-tertiary` + `border-default` + `rounded` (4px)
- Padding: 2px 8px
- Mono font, uppercase

### Scroll Area
- Custom scrollbar: 4px wide, `bg-muted` track, `text-secondary` thumb
- No visible track background

## Responsive Breakpoints

| Name | Width | Layout |
|------|-------|--------|
| Mobile | < 768px | Single pane, bottom bar, tab switcher |
| Tablet | 768-1024px | Two pane, sidebar collapsible |
| Desktop | > 1024px | Two pane, fixed sidebar |

## Icons

Lucide icons only. No emoji in production UI (except user-facing content like transcript speaker labels).
