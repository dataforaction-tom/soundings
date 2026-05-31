# UI Design Plan — Phase 5b (Beautiful UI)

> Last updated: 2026-05-24
> Status: **In progress** — Design review complete, implementation starting

## Objective

Apply Good Ship branding to Soundings — transform the functional, minimal UI into something beautiful that fits the design family (good-ship.co.uk, ourglade.app, swells.app, impact-path.vercel.app, driftforms.app).

## Design Principles (from Good Ship sites)

| Element | Good Ship Style |
|---------|-----------------|
| **Colors** | Earthy, warm: dark navy #1a2f4e as primary, green accents (#4a7c59), cream/off-white backgrounds (#faf9f6) |
| **Typography** | Clean sans-serif with varied weights for hierarchy, generous line-height |
| **Layout** | Generous whitespace, clear hierarchy, card-based components with subtle shadows |
| **Tone** | Friendly, informative, approachable |
| **Components** | Cards with rounded corners (~8px), subtle shadows, careful spacing |

## Implementation Scope

### Priority 1: Foundation (Core Styles)

- [x] **Define CSS custom properties** in `ui/src/styles/global.css`
  - `--color-primary: #1a2f4e` (dark navy)
  - `--color-accent: #4a7c59` (green)
  - `--color-bg: #faf9f6` (warm cream)
  - `--color-surface: #ffffff` (white for cards)
  - `--color-text: #2d2d2d` (warm charcoal)
  - `--color-muted: #6b7280` (gray for secondary text)
  - `--color-border: #e5e5e5` (subtle borders)
  - `--radius: 8px` (rounded corners)
  - `--shadow: 0 2px 8px rgba(0,0,0,0.08)` (subtle shadows)
  - `--space-xs: 0.25rem`, `--space-sm: 0.5rem`, `--space-md: 1rem`, `--space-lg: 1.5rem`, `--space-xl: 2rem`, `--space-2xl: 3rem`

- [x] **Update Base.astro layout**
  - Apply `var(--color-bg)` as page background
  - Use `--space-2xl` for vertical rhythm
  - Improve header styling (logo + tagline)

- [x] **Apply global typography**
  - Better heading sizes and weights
  - Consistent line-heights
  - Link styling with accent color

### Priority 2: Key Components

- [x] **Improve ConsentBanner.astro**
  - Warm background color
  - Better button styling
  - Make it feel like a feature, not a warning

- [x] **Style IndicatorCard.astro**
  - Card surface with subtle shadow
  - Better spacing between elements
  - Improve badge styling

- [x] **Polish CompareChart.astro**
  - Updated chart colors to green accent
  - Improved axis styling
  - Better color coding

### Priority 3: Pages

- [x] **Enhanced Homepage (index.astro)**
  - More inviting search form with larger input
  - Add helpful placeholder text / examples
  - Warm background, better spacing

- [x] **Place Detail Page (place/[id].astro)**
  - Better section spacing
  - Improve card grid layout
  - Add subtle separators between sections

- [x] **About Page (about.astro)** — lead intro, sectioned headers with accent
  underline, inline-code styling, consent/link list rhythm

## File Changes

| File | Change |
|------|--------|
| `ui/src/styles/global.css` | CREATE — CSS custom properties + base styles |
| `ui/src/layouts/Base.astro` | UPDATE — Apply global styles, improve header |
| `ui/src/components/ConsentBanner.astro` | UPDATE — Warm styling |
| `ui/src/components/IndicatorCard.astro` | UPDATE — Card polish |
| `ui/src/components/CompareChart.astro` | UPDATE — Tooltips + axis styling |
| `ui/src/pages/index.astro` | UPDATE — Search form polish |
| `ui/src/pages/place/[id].astro` | UPDATE — Layout spacing |
| `ui/src/pages/about.astro` | UPDATE — Typography improvements |

## Testing

- [ ] Manual browser testing on `make ui-dev`
- [ ] Verify responsive on mobile
- [ ] Check contrast ratios for accessibility

## Notes

- Keep functional behavior unchanged — design only
- Don't add new dependencies (use existing CSS)
- Test charts still render correctly after styling changes
