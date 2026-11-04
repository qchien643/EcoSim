---
name: "Nocturne Stage"
description: "Live-event design at midnight. Deep ink-blue surfaces, oversized Bricolage Grotesque headlines with negative tracking, a single electric magenta that reads like a stage spotlight on a single name. Built for festivals, concert series, and event platforms that earn their drama from typography, not glow."
tags: [dark, event, bold, modern, premium]
colors:
  primary:   "#f4f1ec"
  secondary: "#8a8a9c"
  tertiary:  "#f4f1ec"
  neutral:   "#15151c"
  surface:   "#0c0c12"
typography:
  display: "Bricolage Grotesque"
  body:    Inter
  mono:    "JetBrains Mono"
  scale:
    hero: "6.5rem / 0.9 / 800 / -0.045em"
    h1:   "3.75rem / 0.98 / 700 / -0.035em"
    h2:   "1.875rem / 1.15 / 600 / -0.02em"
    body: "1rem / 1.55 / 400 / -0.005em"
radius:
  sm: 2px
  md: 4px
  lg: 6px
  pill: 9999px
shadows:
  card:   "rgba(0,0,0,0.45) 0 1px 0 inset, rgba(0,0,0,0.6) 0 8px 24px -12px"
  button: "rgba(255,46,126,0.30) 0 8px 24px -12px"
borders:
  card:    "1px solid rgba(244,241,236,0.08)"
  divider: rgba(244,241,236,0.10)
buttons:
  primary:
    background: #ff2e7e
    color: #0c0c12
    border: none
    shape: sharp
    padding: 13px 26px
    font: 700 / 0.8125rem / 0.06em
    uppercase: true
  secondary:
    background: #1c1c26
    color: #f4f1ec
    border: 1px solid rgba(244,241,236,0.14)
    shape: sharp
    padding: 13px 26px
    font: 600 / 0.8125rem / 0.06em
    uppercase: true
  outline:
    background: transparent
    color: #f4f1ec
    border: 1px solid rgba(244,241,236,0.22)
    shape: sharp
    padding: 13px 26px
    font: 600 / 0.8125rem / 0.06em
    uppercase: true
  ghost:
    background: transparent
    color: #8a8a9c
    border: none
    shape: sharp
    padding: 13px 18px
    font: 600 / 0.8125rem / 0.06em
    uppercase: true
charts:
  variant: "thin-bars"
  stroke_width: 1.5
  fill_opacity: 0.1
  gridlines: false
  bar_gap: 8px
  highlight: single
  dot_marker: true
fonts_url: "https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700;12..96,800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
dependencies: ["lucide-react"]
---

# Nocturne Stage

## AI Build Instructions

> **Read this section before writing any code.** The rules below
> are non-negotiable. Every value used in the UI must come from this
> file's frontmatter — never substitute, approximate, or invent new
> colors, fonts, radii, or shadows. If a value is missing, ask the
> user before adding one.

### 1 · Your role

You are building UI for a project that has adopted **Nocturne Stage** as its
design system. Treat `DESIGN.md` as the single source of truth.
Your job is to translate the user's product requirements into
components and pages that look like they were designed by the same
person who authored this file.

### 2 · Token compliance

- Pull every color, font family, radius, shadow, and spacing value
  from the frontmatter at the top of this file.
- Use semantic roles (e.g. `primary`, `accent`, `muted`) — never
  hard-code hex values that bypass the system.
- When a token can be expressed as a CSS variable, declare it once
  in your global stylesheet and reference it everywhere downstream.
- The Google Fonts `<link>` is provided in the Typography section.
  Add it to `<head>` before any component renders.

### 3 · Component recipes

Use these recipes verbatim when building the corresponding component.

#### Buttons

Four variants are defined. Pick one — never blend variants or invent a fifth.

- **Primary** — sharp shape, bg `#ff2e7e`, text `#0c0c12`, padding `13px 26px`, weight `700`, uppercased.
- **Secondary** — sharp shape, bg `#1c1c26`, text `#f4f1ec`, border `1px solid rgba(244,241,236,0.14)`, padding `13px 26px`, weight `600`, uppercased.
- **Outline** — sharp shape, text `#f4f1ec`, border `1px solid rgba(244,241,236,0.22)`, padding `13px 26px`, weight `600`, uppercased.
- **Ghost** — sharp shape, text `#8a8a9c`, padding `13px 18px`, weight `600`, uppercased.

Reach for **primary** as the single dominant CTA per screen.
**Secondary** for the supporting action. **Outline** for tertiary
actions in toolbars. **Ghost** for inline links and table actions.

#### Cards

- Background: `#0c0c12`
- Border: `1px solid rgba(244,241,236,0.08)`
- Shadow: `rgba(0,0,0,0.45) 0 1px 0 inset, rgba(0,0,0,0.6) 0 8px 24px -12px`
- Radius: `radius.lg` (`6px`)
- Internal padding: `20px` for compact cards, `24–28px` for content cards.

#### Tabs

Variant: `underline`. Flat row of labels. Active tab gets a 2px underline in the accent color — no fill.

#### Charts

- Bar/line variant: `thin-bars`
- No gridlines — let the bars/lines carry the data.
- Highlight strategy: `single` — emphasize a single bar/point per chart.

#### Typography pairings

- **Display (`Bricolage Grotesque`)** — h1, h2, hero headlines, brand wordmarks.
- **Body (`Inter`)** — paragraphs, labels, button text, form inputs.
- **Mono (`JetBrains Mono`)** — code, eyebrows, metadata, numerals in tables.

### 4 · Hard constraints

Never do any of the following without explicit instruction from the user:

- Introduce a new color, font, radius, or shadow that isn't declared above.
- Mix this system with another (e.g. don't paste in Material or Bootstrap defaults).
- Use generic gradient defaults (purple→blue, peach→pink) — they break the system's voice.
- Reach for emoji icons. Use a consistent icon library and size icons in line with body type.
- Add motion that exceeds the system's restraint — keep transitions short (≤200ms) and subtle.

### 5 · Before you finish — verify

Run through this checklist for every screen you produce:

- [ ] Every color used appears in the Colors table above.
- [ ] Headlines use the display font; body copy uses the body font.
- [ ] Buttons match one of the declared variants exactly (shape, padding, weight).
- [ ] Border-radius values come from `radius.sm` / `radius.md` / `radius.lg` / `radius.pill`.
- [ ] Cards and dividers use the declared border + shadow tokens.
- [ ] No values were invented; if you needed something missing, you stopped and asked.

---

## 1. Atmosphere

Nocturne Stage is what a festival lineup poster looks like at midnight. The page is deep ink-blue `#0c0c12` — colder than black, warmer than navy. Headlines run in Bricolage Grotesque at 104px, weight 800, with -0.045em tracking that compresses the letterforms into a single gestural mass. Body sits in Inter at 16px, ink-secondary so it never competes with the display. The single accent is electric magenta `#ff2e7e` — used only on the headline CTA and as a 1px underline beneath the headlining act. No glow halos, no neon outlines, no purple-pink gradients.

The discipline is in the contrast: massive display type doing all the work, magenta used like a spotlight cue on a single name.

**Signature moves**
- Bricolage Grotesque 800 at 104px hero with optical sizing — the typography IS the poster
- Magenta `#ff2e7e` reserved for the primary CTA and a 1px underline under one name per screen
- Sharp 0-2px corners — clubs and venues, not soft saas
- Buttons in uppercase 0.06em tracking — that's the ticket-stub voice
- Deep ink-blue `#0c0c12` background — never pure black, never grey

## 2. Palette

### Surfaces
- **Stage Black** `#0c0c12` — page background, deeper than navy
- **Stage Lift** `#15151c` — section bands
- **Card** `#1c1c26` — secondary surfaces, secondary button
- **Hairline** `rgba(244,241,236,0.08)` — every divider

### Ink (light on dark)
- **Bone** `#f4f1ec` — text, headings (warm, never pure white)
- **Bone 50** `#8a8a9c` — secondary text, ghost buttons

### Accent
- **Magenta** `#ff2e7e` — primary CTA, headlining-act underline
- **Magenta Soft** `rgba(255,46,126,0.16)` — focus ring, hovered card border

## 3. Typography

| Role | Font | Size | Weight | Leading | Tracking |
|------|------|------|--------|---------|----------|
| Hero | Bricolage Grotesque | 104px | 800 | 0.9 | -0.045em |
| H1 | Bricolage Grotesque | 60px | 700 | 0.98 | -0.035em |
| H2 | Bricolage Grotesque | 30px | 600 | 1.15 | -0.02em |
| Body | Inter | 16px | 400 | 1.55 | -0.005em |
| UI / Button | Inter | 13px | 700 | 1.2 | 0.06em uppercase |
| Mono / Date | JetBrains Mono | 11px | 500 | 1.0 | 0.10em uppercase |

Bricolage Grotesque does all display work — its variable weight + optical sizing earn the drama without color or glow.

## 4. Buttons

### Primary (Magenta Cue)
```css
background: #ff2e7e;
color: #0c0c12;
padding: 13px 26px;
border-radius: 4px;
font-weight: 700;
text-transform: uppercase;
letter-spacing: 0.06em;
box-shadow: rgba(255,46,126,0.30) 0 8px 24px -12px;
```

The shadow is magenta-tinted — that's the only "glow" in the entire system, and it's a soft drop shadow, not an outline halo.

### Secondary (Card Surface)
- `#1c1c26` background, 1px hairline at 14% bone, bone text — same uppercase voice

### Outline & Ghost
- Outline: transparent, 1px hairline at 22% bone
- Ghost: no border, bone-50 text, hover lifts to bone

## 5. Cards

```css
background: #15151c;
border: 1px solid rgba(244,241,236,0.08);
border-radius: 6px;
box-shadow:
  rgba(0,0,0,0.45) 0 1px 0 inset,
  rgba(0,0,0,0.6) 0 8px 24px -12px;
```

The 1px black inset highlight at the top edge is the dark-mode equivalent of the metallic catch-light — it sells depth without adding chrome.

Featured cards (the headlining act) get a 1px magenta underline at the bottom — that is the only second use of the accent.

## 6. Charts

Thin precise bars (3px wide, 8px gap). One bar in magenta, others in 22% bone. NO gridlines. Line charts at 1.5px bone with a 10% magenta fill, ending in a magenta dot marker. Y-axis labels in JetBrains Mono uppercase 11px.

## 7. Tabs

Underline 1.5px in magenta for the active state. Inactive tabs are bone-50 in uppercase 0.06em tracking. Hover = bone text, no underline.

## 8. Spacing

- Base 4px
- Scale: `4, 8, 12, 16, 24, 32, 48, 64, 96, 128`
- Section padding: 128px desktop, 64px mobile — the negative space is part of the stage

## 9. Do's & don'ts

✅ **Do**
- Hold Bricolage Grotesque at 800 / -0.045em for the hero — that compression IS the brand
- Use deep ink-blue `#0c0c12` — pure black reads as terminal, navy reads as corporate
- Reserve magenta for the primary CTA + one headline underline per screen
- Keep all UI labels uppercase 0.06em — that's the ticket-stub typography

❌ **Don't**
- Add neon glow outlines — magenta is a spotlight, not a tube light
- Use a second accent (cyan, lime, etc.) — the page is deep blue + bone + magenta, full stop
- Use pill buttons — sharp 4px is the venue voice
- Use Bricolage at less than 600 in display — anything lighter loses the gestural mass

---

## Tokens

> Generated from the same source the live preview renders from.
> Treat the values below as the contract — never substitute approximations.

### Colors

| Role      | Value |
|-----------|-------|
| primary   | `#f4f1ec` |
| secondary | `#8a8a9c` |
| tertiary  | `#f4f1ec` |
| neutral   | `#15151c` |
| surface   | `#0c0c12` |

### Typography

- **Display:** Bricolage Grotesque
- **Body:** Inter
- **Mono:** JetBrains Mono

| Role | size / leading / weight / tracking |
|------|------------------------------------|
| Hero | 6.5rem / 0.9 / 800 / -0.045em |
| H1   | 3.75rem / 0.98 / 700 / -0.035em |
| H2   | 1.875rem / 1.15 / 600 / -0.02em |
| Body | 1rem / 1.55 / 400 / -0.005em |

### Radius

- sm: `2px`
- md: `4px`
- lg: `6px`
- pill: `9999px`

### Shadows

- **card:** `rgba(0,0,0,0.45) 0 1px 0 inset, rgba(0,0,0,0.6) 0 8px 24px -12px`
- **button:** `rgba(255,46,126,0.30) 0 8px 24px -12px`

### Borders

- **card:** `1px solid rgba(244,241,236,0.08)`
- **divider:** `rgba(244,241,236,0.10)`

### Buttons

Four variants, each fully tokenized. The preview renders from these exact values.

#### Primary

| Property | Value |
|----------|-------|
| shape | `sharp` |
| background | `#ff2e7e` |
| color | `#0c0c12` |
| border | `none` |
| padding | `13px 26px` |
| fontWeight | `700` |
| fontSize | `0.8125rem` |
| tracking | `0.06em` |
| uppercase | `true` |

#### Secondary

| Property | Value |
|----------|-------|
| shape | `sharp` |
| background | `#1c1c26` |
| color | `#f4f1ec` |
| border | `1px solid rgba(244,241,236,0.14)` |
| padding | `13px 26px` |
| fontWeight | `600` |
| fontSize | `0.8125rem` |
| tracking | `0.06em` |
| uppercase | `true` |

#### Outline

| Property | Value |
|----------|-------|
| shape | `sharp` |
| background | `transparent` |
| color | `#f4f1ec` |
| border | `1px solid rgba(244,241,236,0.22)` |
| padding | `13px 26px` |
| fontWeight | `600` |
| fontSize | `0.8125rem` |
| tracking | `0.06em` |
| uppercase | `true` |

#### Ghost

| Property | Value |
|----------|-------|
| shape | `sharp` |
| background | `transparent` |
| color | `#8a8a9c` |
| border | `none` |
| padding | `13px 18px` |
| fontWeight | `600` |
| fontSize | `0.8125rem` |
| tracking | `0.06em` |
| uppercase | `true` |

### Charts

| Property | Value |
|----------|-------|
| variant | `thin-bars` |
| strokeWidth | `1.5` |
| fillOpacity | `0.1` |
| gridlines | `false` |
| barGap | `8px` |
| highlight | `single` |
| dotMarker | `true` |

---

## Pro tokens

> Production-fidelity tokens. States, density, motion, elevation,
> content rules and a measured WCAG contract — derived from the
> resting tokens unless explicitly authored.

### States

#### Button

- **hover** — shadow: `0 0 24px -4px rgba(244, 241, 236, 0.5), 0 8px 24px -8px rgba(0,0,0,0.6)`, filter: `brightness(1.1)`
- **focus** — outline: `1.5px solid #f4f1ec`, outline-offset: `3px`
- **active** — transform: `translateY(1px)`, filter: `brightness(0.92)`
- **disabled** — opacity: `0.35`, filter: `saturate(0.4)`
- **loading** — opacity: `0.6`
- **selected** — bg: `#f4f1ec`, color: `#0A0A0A`

#### Input

- **hover** — border: `1px solid rgba(244, 241, 236, 0.5)`
- **focus** — border: `1px solid #f4f1ec`, shadow: `0 0 0 3px rgba(244, 241, 236, 0.2)`
- **disabled** — opacity: `0.35`
- **error** — border: `1px solid #F87171`, shadow: `0 0 0 3px rgba(248,113,113,0.2)`

#### Card

- **hover** — shadow: `0 16px 40px -12px rgba(0,0,0,0.7), 0 0 0 1px rgba(244, 241, 236, 0.18)`, transform: `translateY(-2px)`
- **selected** — border: `1px solid #f4f1ec`, shadow: `0 0 0 1px #f4f1ec`
- **dragging** — shadow: `0 24px 60px -16px rgba(0,0,0,0.85)`, transform: `scale(1.02)`, opacity: `0.85`

#### Tab

- **hover** — color: `#f4f1ec`
- **focus** — outline: `1.5px solid #f4f1ec`, outline-offset: `2px`
- **selected** — color: `#f4f1ec`, border: `0 0 1.5px 0 solid #f4f1ec`

### Density

| Mode | padding × | row × | body | radius × | Use for |
|------|-----------|-------|------|----------|---------|
| compact | 0.72 | 0.78 | 0.8125rem | 0.85 | Information-dense — tables, IDEs, dashboards |
| comfortable | 1 | 1 | 0.9375rem | — | Default — most product UI |
| spacious | 1.35 | 1.3 | 1rem | 1.15 | Editorial — marketing, long-form, settings |

### Motion

**Signature — Glide.** Fließende, leicht beschleunigte Übergänge mit Accent-Glow auf hover. Premium-Feeling durch kontrollierte Lichtspiele.

```css
transition: all 280ms cubic-bezier(0.32, 0.72, 0, 1);
```

| Token | Value |
|-------|-------|
| duration.instant | `100ms` |
| duration.fast | `180ms` |
| duration.base | `280ms` |
| duration.slow | `450ms` |
| easing.standard | `cubic-bezier(0.32, 0.72, 0, 1)` |
| easing.decelerate | `cubic-bezier(0.0, 0, 0.2, 1)` |
| easing.accelerate | `cubic-bezier(0.4, 0, 1, 1)` |
| easing.spring | `cubic-bezier(0.5, 1.25, 0.55, 1)` |

### Elevation

Five-level scale, system-specific recipe.

| Level | Shadow | Recipe |
|-------|--------|--------|
| level0 | `none` | Flat — Hairline mit Accent-Hauch. |
| level1 | `0 2px 4px rgba(0,0,0,0.45)` | Subtle drop — list items. |
| level2 | `0 12px 28px -8px rgba(0,0,0,0.6)` | Popover — vom Canvas gelöst. |
| level3 | `0 20px 48px -12px rgba(0,0,0,0.7), 0 0 32px -8px rgba(244, 241, 236, 0.25)` | Sheet — Accent-Halo. |
| level4 | `0 40px 96px -16px rgba(0,0,0,0.85), 0 0 64px -12px rgba(244, 241, 236, 0.4)` | Modal — voller Accent-Rim, dramatisch. |

### Content

- **measure:** `66ch` (max line length for body prose)
- **paragraph spacing:** `1.3em`
- **list indent:** `1.5em`
- **list gap:** `0.5em`
- **link:** color `#f4f1ec`, underline `hover`
- **blockquote:** border `2px solid #f4f1ec`, padding `0.8em 1.2em`
- **code:** background `rgba(244, 241, 236, 0.12)`, color `#f4f1ec`

### Accessibility (WCAG 2.1)

**Overall:** AA

| Pair | Ratio | Required | Grade | Suggested fix |
|------|-------|----------|-------|---------------|
| Body text on surface | 17.31:1 | AA | AAA | — |
| Body text on canvas | 16.13:1 | AA | AAA | — |
| Muted text on surface | 5.75:1 | AA | AA | — |
| Accent on surface | 17.31:1 | AA-Large | AAA | — |
| Accent on canvas | 16.13:1 | AA-Large | AAA | — |
