---
name: Nocturne Focus
colors:
  surface: '#111317'
  surface-dim: '#111317'
  surface-bright: '#37393e'
  surface-container-lowest: '#0c0e12'
  surface-container-low: '#1a1c20'
  surface-container: '#1e2024'
  surface-container-high: '#282a2e'
  surface-container-highest: '#333539'
  on-surface: '#e2e2e8'
  on-surface-variant: '#c6c5d7'
  inverse-surface: '#e2e2e8'
  inverse-on-surface: '#2f3035'
  outline: '#8f8fa0'
  outline-variant: '#454655'
  surface-tint: '#bec2ff'
  primary: '#bec2ff'
  on-primary: '#000da4'
  primary-container: '#5865f2'
  on-primary-container: '#fffdff'
  inverse-primary: '#3f4cda'
  secondary: '#b6c4ff'
  on-secondary: '#092977'
  secondary-container: '#28418e'
  on-secondary-container: '#9db2ff'
  tertiary: '#b9c3ff'
  on-tertiary: '#0c2680'
  tertiary-container: '#5c6fc9'
  on-tertiary-container: '#fffdff'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e0e0ff'
  primary-fixed-dim: '#bec2ff'
  on-primary-fixed: '#000569'
  on-primary-fixed-variant: '#222fc2'
  secondary-fixed: '#dce1ff'
  secondary-fixed-dim: '#b6c4ff'
  on-secondary-fixed: '#00164f'
  on-secondary-fixed-variant: '#28418e'
  tertiary-fixed: '#dde1ff'
  tertiary-fixed-dim: '#b9c3ff'
  on-tertiary-fixed: '#001257'
  on-tertiary-fixed-variant: '#2a3f97'
  background: '#111317'
  on-background: '#e2e2e8'
  surface-variant: '#333539'
typography:
  display:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.03em
  display-mobile:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 30px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  title-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
  space-2xl: 3rem
---

## Brand & Style
The design system manifests an intimate, high-efficiency digital sanctuary designed for deep academic and intellectual sessions. Merging the architectural material discipline of Windows 11 Fluent Design with the tactile responsiveness of modern productivity utilities (Raycast, Arc, Discord), the aesthetic prioritizes visual quiet, low eye-strain ergonomics, and tactical clarity.

### Aesthetic Foundation
- **Materiality:** Mica and Acrylic surface simulation. Distinct optical tiers distinguish ambient background contexts from interactive workspaces and transient HUD layers.
- **Tone:** Academic, focused, nocturnal, precise, and unobtrusive.
- **Atmosphere:** Dark, luminous, and controlled. Content acts as the primary light source across deep graphite and slate backdrops, accented by restrained indigo glows.

## Colors
The palette leverages deep, low-luminance slate neutrals paired with electric, focused indigo and periwinkle accents to minimize fatigue during long-duration study.

### Palette Architecture
- **Mica Base Canvas (`#0F1115`):** Structural canvas layer. Represents the deepest visual plane.
- **Acrylic Sidebar / Panel (`#181C21`):** Intermediate working containers and tool bays with optical noise/translucency characteristics.
- **Layered Card Surface (`#21262D`):** Elevated resting plane for discrete task blocks, flashcard decks, and active study modules.
- **Card Interactive / Hover (`#293038`):** Dynamic feedback state for interactive structural blocks.
- **Primary Indigo (`#5865F2`):** Primary command anchor, active focus state, and principal action vector.
- **Secondary Periwinkle (`#7289DA`):** Supporting hierarchy, muted badges, and secondary highlights.
- **Accent Electric Blue (`#8EA1FF`):** Micro-indicators, timer completions, and high-priority emphasis targets.
- **Semantic Signals:**
  - **Success Emerald (`#43B581`):** Verified solutions, completed study goals, streak counts.
  - **Warning Amber (`#FAA61A`):** Session drift alerts, expiring timers, review reminders.
  - **Error Rose (`#F04747`):** Retention breaks, critical blockers, destructive options.
- **Subtle Surface Line (`rgba(255, 255, 255, 0.08)`):** Defines physical containment boundaries without introducing visual friction.

## Typography
The system employs `Inter` for interface elements and editorial copy, maintaining optical clarity at variable scales. Technical metadata, timestamps, analytics figures, and study session clocks use `JetBrains Mono` to establish clear contextual differentiation between narrative content and operational state.

### Hierarchy & Execution
- **Tracking:** Negative tracking on all display and headline sizes tightens the optical density and reflects desktop OS utility software.
- **Numbers & Metrics:** Statistical reviews, Pomodoro counters, and flashcard counts must always render in tabular monospace via `label-md` or `label-sm`.
- **Contrast Ratios:** Primary body text uses `#FFFFFF` (90% opacity), secondary meta-information sits at `#9BA3AF` (70% opacity), and disabled/placeholder content locks to `#4B5563` (45% opacity).

## Layout & Spacing
The layout model employs a responsive, fluid grid architecture constrained by utility app framing. Structural frames are defined through nested panes, echoing fluent desktop workspace conventions.

### Spatial Grid System
- **Desktop (>= 1200px):** 12-column dynamic layout using `gutter-desktop` (24px) and `margin-desktop` (32px). Persistent navigation panel (`280px` fixed width) alongside flexible modular cards.
- **Tablet (768px - 1199px):** 8-column layout with `margin-tablet` (24px). Sidebar collapses to an icon shelf or slide-out acrylic drawer.
- **Mobile (< 768px):** 4-column layout with single-column vertical stacking, `margin` (16px), and unified command sheets anchored to the bottom.

### Rhythmic Discipline
- Internal padding within elevated cards adheres strictly to `space-lg` (24px) for major modules and `space-md` (16px) for compact widgets.
- Elements grouped within the same semantic block (e.g., input and field label) are separated by `space-xs` (4px) or `space-sm` (8px).

## Elevation & Depth
Depth is realized through structural opacity layering, translucent frosted interfaces, and low-frequency ambient luminescent fills rather than hard drop shadows.

### Layer Tiers
- **Tier 0 (Root Window):** Mica canvas (`#0F1115`). Ground zero; non-interactive structural floor.
- **Tier 1 (Acrylic Workspace):** Panelled containers (`#181C21` with `backdrop-filter: blur(24px)`).
- **Tier 2 (Card Elevation):** Raised content surface (`#21262D`) bounded by an internal hair-line border: `1px solid rgba(255, 255, 255, 0.08)`.
- **Tier 3 (Floating HUD & Menus):** High overlays (`#293038` at 85% opacity with `backdrop-filter: blur(32px)`). Paired with ambient glows: `box-shadow: 0 12px 32px -8px rgba(0, 0, 0, 0.65), 0 0 24px -4px rgba(88, 101, 242, 0.12)`.

### Lighting & Borders
No elements use opaque, heavy borders. Contours are expressed through a uniform single-pixel rim (`rgba(255, 255, 255, 0.08)`) to mimic the reflective chamfers of etched glass lenses. Focused and active nodes project a directional soft indigo halo (`rgba(88, 101, 242, 0.35)` with an 18px blur).

## Shapes
Geometry is disciplined, soft, and modern, anchored by a system-wide baseline curvature of `16px` (`rounded-lg`) for all primary surfaces to echo Windows 11 window corners.

### Radius Assignments
- **Core Cards & Containers (`rounded-lg`):** `16px` (1rem). Applied to main panels, focus modules, and modal dialogues.
- **Nested Controls & Actions (`rounded`):** `8px` (0.5rem). Applied to buttons, input fields, dropdown triggers, and status chips.
- **Interactive Pills (`rounded-xl`):** `24px` (1.5rem). Reserved specifically for global search/command bars (Raycast-style), active timers, and running status indicators.
- **Avatars & Micro Badges:** Fully circular (`50%`).

## Components

### Buttons
- **Primary:** Solid `#5865F2` fill, `#FFFFFF` text, `8px` corner radius. Hover state transitions to `#7289DA` with a persistent soft glow `box-shadow: 0 0 16px rgba(88, 101, 242, 0.4)`. Active state compresses slightly via `transform: scale(0.98)`.
- **Secondary / Ghost:** Transparent surface with `1px solid rgba(255, 255, 255, 0.08)`. Hover state fills with `rgba(255, 255, 255, 0.05)` and brightens the border to `rgba(255, 255, 255, 0.15)`.

### Cards & Study Panels
- Base style uses `#21262D`, `16px` radius, and `1px solid rgba(255, 255, 255, 0.08)`.
- Padding conforms strictly to `24px` (`space-lg`).
- Interactive review cards feature a top-edge highlight (`1px solid rgba(255, 255, 255, 0.12)`) simulating direct downward workspace illumination.

### Chips & Tags
- Height fixed at `24px`, radius `6px`. Background tinted to `rgba(255, 255, 255, 0.04)` with `JetBrains Mono` label text at `10px` (`label-sm`).
- Categorical chips leverage semantic foreground tints (e.g., `#8EA1FF` for Math, `#43B581` for Complete) with matching 10% opacity fills.

### Input Fields & Command Bar
- Surface: `#181C21`, height `40px`, border `1px solid rgba(255, 255, 255, 0.08)`, radius `8px`.
- Raycast-style command bar: Centered HUD component, height `52px`, radius `24px`, background `rgba(24, 28, 33, 0.85)` with `32px` blur and an outer focus ring: `2px solid #5865F2`.

### Checkboxes & Toggle Radios
- Checkboxes: `18x18px` squares, `4px` corner radius, `1px solid rgba(255, 255, 255, 0.2)`. Checked state transitions to `#5865F2` border and fill with an optical white check icon.
- Radio buttons: `18x18px` circles with an internal concentric dot (`6px`) displayed in `#8EA1FF` when active.

### Progress & Timers (Domain Specific)
- **Radial Study Timer:** Deep background track (`rgba(255, 255, 255, 0.05)`), overlaid with a continuous `#5865F2` to `#8EA1FF` stroke gradient and dynamic terminal glow.
- **Streak & Flashcard Counters:** Tabular values using `JetBrains Mono`, enclosed in elevated pill tags with low-intensity ambient Emerald (`#43B581`) or Amber (`#FAA61A`) accents.