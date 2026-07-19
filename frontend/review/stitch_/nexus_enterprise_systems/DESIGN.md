---
name: Nexus Enterprise Systems
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#45464d'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#0051d5'
  on-secondary: '#ffffff'
  secondary-container: '#316bf3'
  on-secondary-container: '#fefcff'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#191c1e'
  on-tertiary-container: '#818486'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#dbe1ff'
  secondary-fixed-dim: '#b4c5ff'
  on-secondary-fixed: '#00174b'
  on-secondary-fixed-variant: '#003ea8'
  tertiary-fixed: '#e0e3e5'
  tertiary-fixed-dim: '#c4c7c9'
  on-tertiary-fixed: '#191c1e'
  on-tertiary-fixed-variant: '#444749'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 64px
  container-max: 1440px
  gutter: 24px
---

## Brand & Style
The design system is engineered for high-stakes enterprise environments where precision and clarity are paramount. The brand personality is authoritative yet unobtrusive, positioning itself as a reliable partner in document analysis and AI-driven workflows. 

The aesthetic is **Modern Corporate**, blending functional minimalism with high-density information architecture. It prioritizes the "content-over-chrome" philosophy, ensuring that the interface recedes to highlight user data and AI insights. By utilizing generous whitespace, a systematic grid, and a restricted palette, the UI evokes an emotional response of focus, professional trust, and operational efficiency.

## Colors
The color palette is built on a foundation of "Slate" and "Indigo" scales to ensure a professional, cool-toned environment. 

- **Primary:** A deep Navy (#0F172A) used for high-level navigation, headers, and text to establish authority.
- **Secondary:** A functional Blue (#2563EB) reserved for primary actions, progress indicators, and active states.
- **Neutral:** A comprehensive range of slate greys handles borders, secondary text, and background layers.
- **Semantic Colors:** Success, Error, and Warning colors are highly saturated to ensure critical AI alerts and document statuses are immediately recognizable against the neutral backdrop.

## Typography
The typography system utilizes **Inter** for its exceptional legibility and neutral, systematic character. It is optimized for long-form reading and data scanning.

- **Scale:** A tight modular scale ensures visual harmony across complex dashboards.
- **Weights:** Use "Regular" (400) for body copy, "Medium" (500) for UI labels, and "Semi-Bold" (600) for headings to create a clear information hierarchy.
- **Readability:** Body text uses a slightly increased line-height (1.5x) to reduce eye fatigue during document reviews. Labels for AI confidence scores or metadata use "Semi-Bold" at smaller sizes to remain legible yet secondary.

## Layout & Spacing
This design system employs a **Fluid-to-Fixed Hybrid Grid**. The application framework uses a fixed left-hand navigation (256px) with a fluid content area that expands up to a maximum container width of 1440px.

- **Grid:** A 12-column grid is used for dashboard layouts, while document viewing modes utilize a centered "Reader" column with auxiliary sidebars.
- **Spacing Rhythm:** An 8pt linear scale governs all padding and margins to ensure mathematical consistency.
- **Breakpoints:** 
  - **Desktop (1280px+):** Full 12-column view with dual sidebars.
  - **Tablet (768px - 1279px):** Collapsed navigation rail; single sidebar for AI results.
  - **Mobile (<767px):** Single-column stacked view; sidebars converted to bottom sheets.

## Elevation & Depth
Elevation is communicated through **Tonal Layering** and subtle, monochromatic shadows. This approach avoids visual clutter while clearly defining the interaction stack.

- **Level 0 (Base):** Background color (#F8FAFC). Used for the main application canvas.
- **Level 1 (Card/Surface):** White (#FFFFFF) surfaces with a 1px border (#E2E8F0). No shadow. Used for standard content blocks.
- **Level 2 (Hover/Active):** White surface with a "Soft Ambient" shadow (Y: 4px, Blur: 6px, Opacity: 0.05, Color: #0F172A). Used for interactive cards and file list items.
- **Level 3 (Overlay):** White surface with a "Deep" shadow (Y: 12px, Blur: 24px, Opacity: 0.1). Used for modals, dropdowns, and AI insight popovers.

## Shapes
The shape language is **Soft** and professional. A standard 0.25rem (4px) border radius is applied to most components to provide a modern feel without appearing overly casual or playful.

- **Small Components:** Checkboxes, tags, and small buttons use a 4px radius.
- **Large Components:** Cards, modals, and file upload zones use an 8px (0.5rem) radius.
- **AI Elements:** Elements specifically generated by AI (like suggested edits) may use slightly more rounded corners (12px) to subtly differentiate machine-generated content from the system chrome.

## Components
Consistent component styling reinforces the system's efficiency and reliability.

- **Buttons:** 
  - *Primary:* Solid Indigo (#2563EB) with white text. 
  - *Secondary:* Ghost style with 1px slate border and slate text.
- **File Uploaders:** Large, dashed-border drop zones using #E2E8F0. Active state transitions to a solid blue border with a light blue tinted background.
- **Document Viewer:** A high-contrast white canvas centered on a light grey background. AI annotations are displayed as subtle highlight overlays that expand into detailed side-cards on click.
- **Sidebars:** Use a "Surface" tier (Level 1) with a vertical 1px border. Navigation items use a 4px left-accent bar in Primary Blue when active.
- **Multi-step Progress:** A horizontal stepper with "Connector Lines." Completed steps use a success-green checkmark; the active step uses a blue-pulsing ring.
- **Inputs:** High-contrast text on white backgrounds with 1px slate borders. Focus state uses a 2px blue ring with 0% offset for maximum visibility.
- **Chips/Badges:** Small, low-contrast pills (e.g., "Draft", "Approved") using semantic colors at 10% opacity for the background and 100% for the text.