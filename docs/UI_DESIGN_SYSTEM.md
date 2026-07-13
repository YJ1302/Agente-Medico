# UI DESIGN SYSTEM — UPeU Internado 360

Visual direction: **clean, light, professional, medical-academic, modern**.
Premium but restrained; suitable for a university. Responsive for laptop, tablet
and mobile. Never an excessively dark interface.

## 1. Color palette (CSS variables in `static/css/style.css`)

| Token | Value | Use |
|-------|-------|-----|
| `--navy` | `#0b2447` | Sidebar, headings, primary brand |
| `--navy-700` | `#123a6b` | Hover/gradient depth |
| `--blue` | `#1d5bbf` | Primary actions, links, active nav |
| `--gold` | `#f2b705` | Accent (badges, active indicator) |
| `--white` / `--surface` | `#ffffff` | Cards, surfaces |
| `--bg` | `#f4f6fb` | App background (light gray) |
| `--text` / `--text-muted` | `#1f2a44` / `#64748b` | Body / secondary text |
| `--success` | `#1a9d64` | Success states |
| `--warning` | `#e8890c` | Warnings |
| `--danger` | `#d33b3b` | Critical alerts |
| `--info` | `#2f6fe0` | Informational |

Status colors always pair a strong foreground with a soft `*-bg` tint for chips
and stat-card icons.

## 2. Typography

- Font stack: `Segoe UI, system-ui, Roboto, Helvetica, Arial, sans-serif`
  (system fonts → fast, offline-friendly).
- Base size 15px; page titles 24px; card titles 16px; stat values 26px bold.

## 3. Layout tokens

| Token | Value |
|-------|-------|
| Sidebar width | 264px (collapsed 76px) |
| Top bar height | 62px |
| Card radius | 14px |
| Shadow (card) | `0 1px 2px rgba(16,24,40,.06)` |
| Content max-width | 1400px |

## 4. Components

- **Stat card** (`.stat-card` + `.tone-*`): icon tile + value + label.
- **Card** (`.card`, `.card-head`): titled content container.
- **Chip** (`.chip` + `.chip-*`): status/labels.
- **Data table** (`table.data` inside `.table-scroll`): horizontally scrollable
  on narrow screens.
- **Alert row** (`.alert-row` + `.a-dot`): severity dot + title + message.
- **Agent run** (`.agent-run`): icon + name + summary + timestamp.
- **Quick actions** (`.quick-action`): icon tiles linking to modules.
- **Period banner** (`.period-banner`): navy→blue gradient with gold accent.
- **Empty state** (`.empty-state`), **loading** (`.spinner`, `.loading-block`).
- **Error pages** (`.error-page`): large code, message, home button.

## 5. Navigation

- Fixed left **sidebar** (navy) with titled sections; active item uses blue
  background + gold inset bar.
- **Collapsible** on desktop (toggle persists via `localStorage`).
- **Top bar**: page name, notifications dropdown (live from `/api/notifications`),
  user menu.
- **Mobile**: sidebar becomes an off-canvas drawer with a backdrop; a hamburger
  button appears; `desktop-only`/`mobile-only` utilities switch controls.

## 6. Responsiveness breakpoints

| Width | Behavior |
|-------|----------|
| ≤1100px | Stat grid → 2 columns; two-column rows stack. |
| ≤820px | Sidebar becomes a drawer; top bar spans full width. |
| ≤520px | Stat grid & quick actions → 1 column; user meta hidden. |

## 7. Charts

Chart.js (CDN). Doughnut for rotation distribution, bar for students by
institution. Series are computed **server-side** and passed as JSON; the
template only renders them. Palette reuses the brand tokens.

## 8. Accessibility & UX

- Sufficient contrast on text and status chips.
- Focus states on inputs (blue ring).
- Buttons and interactive rows have hover/active feedback.
- Icons are decorative accompaniments to text labels (Bootstrap Icons).

## 9. Rules

- No business logic in templates; only iteration and presentation.
- Reuse partials (`sidebar.html`, `topbar.html`) and CSS components.
- Keep the interface light; do not introduce dark backgrounds for content areas.
