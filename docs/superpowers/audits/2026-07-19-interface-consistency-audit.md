# Interface Consistency Audit

Date: 2026-07-19
Scope: `frontend/src` and `frontend/index.html`
Quality bar: production administration workspace
Status: pre-remediation baseline; the findings below were addressed in the same working tree.

## Anti-Patterns Verdict

The interface does not broadly look generated, but three implementation tells weaken the otherwise coherent system: colored side-stripe accents on review findings, a bordered card with a wide hover shadow, and repeated one-off control heights. These are localized rather than structural.

## Audit Health Score

| # | Dimension | Score | Key finding |
|---|-----------|-------|-------------|
| 1 | Accessibility | 3/4 | Labels and focus states are generally present, but several controls are below the 44px touch-target recommendation. |
| 2 | Performance | 3/4 | No obvious render or animation issue; the production bundle still emits an existing large-chunk warning. |
| 3 | Responsive Design | 3/4 | Layouts reflow at established breakpoints, while compact actions remain undersized on touch devices. |
| 4 | Theming | 3/4 | A useful token system exists, but semantic tints and outlines are duplicated as hard-coded colors. |
| 5 | Anti-Patterns | 2/4 | Side-stripe callouts and the bordered wide-shadow card are visible design-system exceptions. |
| **Total** | | **14/20** | **Good - address weak dimensions** |

## Executive Summary

- Issues: 0 P0, 1 P1, 4 P2, 1 P3.
- The systemic problem is control vocabulary drift: buttons and icon actions use heights from 28px to 42px without a consistent density rule.
- The product name is inconsistent between the browser title and visible header.
- Shared tokens and responsive structure are strong foundations and should be preserved.

## Detailed Findings

### [P1] Touch targets are consistently undersized

- Location: `frontend/src/styles/main.css`, `ReviewAssistant.vue`, `ReviewUploadView.vue`, `ReviewConsoleView.vue`, `ClauseCard.vue`
- Category: Accessibility / Responsive
- Impact: Compact icon and suggestion actions are harder to acquire on touch screens and for users with motor impairments.
- Standard: WCAG 2.2 SC 2.5.8 Target Size (Minimum).
- Recommendation: Use a 40px desktop control height and guarantee 44px minimum targets for coarse pointers and mobile breakpoints.
- Suggested command: `$impeccable adapt`

### [P2] Button sizing and alignment use one-off values

- Location: Global Element Plus rules and page-scoped button classes across review and API-backed pages.
- Category: Theming / Responsive
- Impact: Header actions, toolbar actions, and row controls do not share a stable baseline, producing visible vertical misalignment.
- Recommendation: Add shared control-size tokens, align icon sizing, and use them for buttons, tab triggers, toolbar actions, and row actions.
- Suggested command: `$impeccable layout`

### [P2] Review findings use colored side stripes

- Location: `RiskCard.vue` and `ReviewConsoleView.vue`
- Category: Anti-Pattern
- Impact: Severity styling diverges from the full-border and tinted-surface vocabulary used elsewhere.
- Recommendation: Replace side stripes with full subtle borders, semantic surface tints, and leading severity icons or badges.
- Suggested command: `$impeccable quieter`

### [P2] Template card combines border and wide shadow

- Location: `TemplateCard.vue`
- Category: Anti-Pattern
- Impact: The hover elevation feels disconnected from the quiet operational surfaces used throughout the app.
- Recommendation: Keep the border and use color/translation feedback without a wide decorative shadow.
- Suggested command: `$impeccable quieter`

### [P2] Product naming is inconsistent

- Location: `frontend/index.html`, `TopHeader.vue`
- Category: Content / Accessibility
- Impact: Browser title, visible identity, and accessible home label describe different products.
- Recommendation: Standardize all three to `审核智规`.
- Suggested command: `$impeccable clarify`

### [P3] Repeated semantic colors bypass tokens

- Location: Review views and shared chat styles.
- Category: Theming
- Impact: Future visual changes require editing many component-local values and can introduce contrast drift.
- Recommendation: Consolidate recurring danger, action, selected, and subdued tints into semantic tokens where they recur.
- Suggested command: `$impeccable colorize`

## Patterns and Systemic Issues

- Control height is encoded at component level instead of through density and touch-target tokens.
- Review pages introduce semantic tints locally even though the root theme already owns semantic colors.
- Page structure, spacing scale, radii, typography, and responsive side navigation are already consistently implemented.

## Positive Findings

- Interactive controls generally use semantic buttons, labels, ARIA state, and visible focus treatment.
- The application has a coherent root token layer and Element Plus theme bridge.
- Mobile layouts reflow toolbars, navigation, readers, and multi-panel review pages rather than merely shrinking them.
- Motion is restrained and includes a reduced-motion override.

## Recommended Actions

1. **[P1] `$impeccable adapt`**: Guarantee usable touch targets while retaining an efficient desktop density.
2. **[P2] `$impeccable layout`**: Standardize control heights, icon sizes, gaps, and alignment through shared tokens.
3. **[P2] `$impeccable clarify`**: Rename browser and header identity to `审核智规`.
4. **[P2] `$impeccable quieter`**: Remove side-stripe accents and wide decorative hover shadows.
5. **[P3] `$impeccable colorize`**: Promote recurring semantic tints to tokens.
6. **[P2] `$impeccable polish`**: Verify the complete interaction path at desktop and mobile widths.

Re-run `$impeccable audit` after fixes to measure the updated score.
