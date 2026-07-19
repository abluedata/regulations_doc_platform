# Review Prototype Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the Stitch prototype's enterprise visual system to the existing Vue application and add a self-contained four-step review demo flow.

**Architecture:** Keep existing API-backed routes intact inside a new shared application shell. Add an isolated Pinia review store, shared review workflow components, and four lazy-loaded review views that use stable local demo data only. Centralize the visual system in CSS custom properties and Element Plus theme overrides.

**Tech Stack:** Vue 3, TypeScript, Vite, Vue Router, Pinia, Element Plus, Vitest, Vue Test Utils, happy-dom

---

### Task 1: Add the frontend behavior test harness

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`

- [ ] **Step 1: Add the test script and dependencies**

Run:

```powershell
npm install -D vitest @vue/test-utils happy-dom
```

Add this script to `frontend/package.json`:

```json
"test": "vitest run"
```

- [ ] **Step 2: Configure Vitest**

Extend `frontend/vite.config.ts` with:

```ts
/// <reference types="vitest/config" />
export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'happy-dom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

Create `frontend/src/test/setup.ts`:

```ts
import { config } from '@vue/test-utils'

config.global.stubs = {
  teleport: true,
  transition: false,
}
```

- [ ] **Step 3: Verify the empty harness**

Run: `npm test -- --passWithNoTests`

Expected: exit code 0 and no test failures.

- [ ] **Step 4: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/setup.ts
git commit -m "test: add frontend component test harness"
```

### Task 2: Implement the isolated review workflow state

**Files:**
- Create: `frontend/src/stores/review.spec.ts`
- Create: `frontend/src/stores/review.ts`
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Write failing store tests**

Create `frontend/src/stores/review.spec.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReviewStore } from './review'

describe('review store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('moves through the four review steps without exceeding the bounds', () => {
    const store = useReviewStore()
    expect(store.currentStep).toBe(1)
    store.nextStep(); store.nextStep(); store.nextStep(); store.nextStep()
    expect(store.currentStep).toBe(4)
    store.previousStep(); store.previousStep(); store.previousStep(); store.previousStep()
    expect(store.currentStep).toBe(1)
  })

  it('updates template, clauses, tuning and approval state locally', () => {
    const store = useReviewStore()
    store.selectTemplate('mutual-nda')
    store.toggleClause('payment-terms')
    store.setSensitivity(72)
    store.completeAnalysis()
    store.approveDraft()
    expect(store.selectedTemplateId).toBe('mutual-nda')
    expect(store.clauses.find((item) => item.id === 'payment-terms')?.enabled).toBe(false)
    expect(store.sensitivity).toBe(72)
    expect(store.analysisStatus).toBe('approved')
  })
})
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `npm test -- src/stores/review.spec.ts`

Expected: FAIL because `./review` does not exist.

- [ ] **Step 3: Add the review types and store**

Add these definitions to `frontend/src/types/index.ts`:

```ts
export type ReviewAnalysisStatus = 'idle' | 'running' | 'complete' | 'approved' | 'rejected'
export interface ReviewFile { id: string; name: string; size: string; progress: number; status: 'ready' | 'uploading' | 'queued' }
export interface ReviewTemplate { id: string; name: string; category: string; description: string; checks: number; icon: string; popular?: boolean }
export interface ReviewClause { id: string; group: 'finance' | 'compliance'; title: string; description: string; enabled: boolean; priority?: 'high'; threshold?: string; disabled?: boolean }
export interface ReviewRisk { id: string; level: 'high' | 'medium' | 'low'; section: string; title: string; description: string; currentText?: string; referenceText?: string }
```

Create `frontend/src/stores/review.ts` with stable Chinese demo arrays matching the names and values visible in the four prototype screenshots and these public actions:

```ts
export const useReviewStore = defineStore('review', () => {
  const currentStep = ref(1)
  const selectedTemplateId = ref('mutual-nda')
  const sensitivity = ref(85)
  const analysisStatus = ref<ReviewAnalysisStatus>('idle')
  const files = ref<ReviewFile[]>(DEMO_FILES.map((item) => ({ ...item })))
  const templates = ref<ReviewTemplate[]>(DEMO_TEMPLATES.map((item) => ({ ...item })))
  const clauses = ref<ReviewClause[]>(DEMO_CLAUSES.map((item) => ({ ...item })))
  const risks = ref<ReviewRisk[]>(DEMO_RISKS.map((item) => ({ ...item })))

  function nextStep() { currentStep.value = Math.min(4, currentStep.value + 1) }
  function previousStep() { currentStep.value = Math.max(1, currentStep.value - 1) }
  function goToStep(step: number) { currentStep.value = Math.min(4, Math.max(1, step)) }
  function selectTemplate(id: string) { selectedTemplateId.value = id }
  function toggleClause(id: string) {
    const clause = clauses.value.find((item) => item.id === id)
    if (clause) clause.enabled = !clause.enabled
  }
  function setSensitivity(value: number) { sensitivity.value = value }
  function completeAnalysis() { analysisStatus.value = 'complete' }
  function approveDraft() { analysisStatus.value = 'approved' }
  function rejectChanges() { analysisStatus.value = 'rejected' }

  return { currentStep, selectedTemplateId, sensitivity, analysisStatus, files,
    templates, clauses, risks, nextStep, previousStep, goToStep, selectTemplate,
    toggleClause, setSensitivity, completeAnalysis, approveDraft, rejectChanges }
})
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm test -- src/stores/review.spec.ts`

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/types/index.ts frontend/src/stores/review.ts frontend/src/stores/review.spec.ts
git commit -m "feat: add local review workflow state"
```

### Task 3: Add review routes and the shared application shell

**Files:**
- Create: `frontend/src/router/routes.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Create: `frontend/src/views/review/ReviewUploadView.vue`
- Create: `frontend/src/views/review/ReviewTemplatesView.vue`
- Create: `frontend/src/views/review/ReviewRulesView.vue`
- Create: `frontend/src/views/review/ReviewConsoleView.vue`
- Create: `frontend/src/components/layout/TopHeader.vue`
- Create: `frontend/src/components/layout/SideNavigation.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles/main.css`

- [ ] **Step 1: Write a failing route contract test**

Create `frontend/src/router/routes.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import router from './index'

describe('review routes', () => {
  it('registers the complete four-step workflow', () => {
    expect(router.getRoutes().filter((route) => route.path.startsWith('/review/')).map((route) => route.path).sort())
      .toEqual(['/review/console', '/review/rules', '/review/templates', '/review/upload'])
  })
})
```

- [ ] **Step 2: Run the route test and verify RED**

Run: `npm test -- src/router/routes.spec.ts`

Expected: FAIL with an empty review route list.

- [ ] **Step 3: Register lazy review routes**

Add these route records:

```ts
{ path: '/review/upload', name: 'review-upload', component: () => import('@/views/review/ReviewUploadView.vue'), meta: { title: '文档上传', reviewStep: 1 } },
{ path: '/review/templates', name: 'review-templates', component: () => import('@/views/review/ReviewTemplatesView.vue'), meta: { title: '范本选择', reviewStep: 2 } },
{ path: '/review/rules', name: 'review-rules', component: () => import('@/views/review/ReviewRulesView.vue'), meta: { title: '条款设置', reviewStep: 3 } },
{ path: '/review/console', name: 'review-console', component: () => import('@/views/review/ReviewConsoleView.vue'), meta: { title: '智能审查', reviewStep: 4 } },
```

Create the four view modules with a minimal heading matching each route title. Task 5 replaces each minimal template after its page test fails.

- [ ] **Step 4: Implement the shared shell and design tokens**

Replace emoji navigation with Element Plus icons. Add `TopHeader` and `SideNavigation`, with route-aware active states and an accessible mobile menu button. Update `App.vue` to render the shell around `router-view`.

Define the prototype token set in `main.css`:

```css
:root {
  --app-bg: #f8f9ff;
  --surface: #ffffff;
  --surface-low: #f1f5fd;
  --surface-high: #e6eefb;
  --ink: #0b1c30;
  --ink-muted: #4d5f73;
  --outline: #c4c7c9;
  --outline-soft: #dbe3ef;
  --action: #0b57d0;
  --action-hover: #0848ad;
  --action-soft: #d8e6ff;
  --success: #14804a;
  --warning: #a15c00;
  --danger: #ba1a1a;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --header-height: 64px;
  --sidebar-width: 256px;
}
```

Include Element Plus button/input/select/table/tag overrides, visible focus rings, responsive shell breakpoints, and reduced-motion handling.

- [ ] **Step 5: Run route tests and build**

Run: `npm test -- src/router/routes.spec.ts`

Expected: 1 test passes.

Run: `npm run build`

Expected: build exits 0.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/router frontend/src/components/layout frontend/src/App.vue frontend/src/styles/main.css
git commit -m "feat: add enterprise application shell"
```

### Task 4: Build shared review workflow components

**Files:**
- Create: `frontend/src/components/review/ReviewStepper.spec.ts`
- Create: `frontend/src/components/review/ReviewStepper.vue`
- Create: `frontend/src/components/review/ReviewFooter.vue`
- Create: `frontend/src/components/review/TemplateCard.vue`
- Create: `frontend/src/components/review/ClauseCard.vue`
- Create: `frontend/src/components/review/RiskCard.vue`

- [ ] **Step 1: Write the failing stepper behavior test**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReviewStepper from './ReviewStepper.vue'

describe('ReviewStepper', () => {
  it('marks completed, active and upcoming steps', () => {
    const wrapper = mount(ReviewStepper, { props: { current: 3 } })
    expect(wrapper.findAll('[data-state="complete"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-state="active"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-state="upcoming"]')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm test -- src/components/review/ReviewStepper.spec.ts`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement shared components**

Create `ReviewStepper.vue` with a typed `current: number` prop, a fixed array of labels “文档上传 / 范本选择 / 条款设置 / 智能审查”, and `data-state` values computed as `complete`, `active`, or `upcoming`. Create `ReviewFooter.vue` with `previousLabel`, `nextLabel`, `previousDisabled`, and `nextDisabled` props plus `previous` and `next` emits. Create typed `TemplateCard`, `ClauseCard`, and `RiskCard` components using the interfaces from Task 2; each card uses a semantic button or checkbox and emits only its record ID. Use Element Plus icons and `aria-label` text on every icon-only button.

- [ ] **Step 4: Run component tests and build**

Run: `npm test -- src/components/review/ReviewStepper.spec.ts`

Expected: 1 test passes.

Run: `npm run build`

Expected: build exits 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/review
git commit -m "feat: add shared review workflow components"
```

### Task 5: Recreate the four Stitch prototype pages

**Files:**
- Create: `frontend/src/views/review/ReviewUploadView.vue`
- Create: `frontend/src/views/review/ReviewTemplatesView.vue`
- Create: `frontend/src/views/review/ReviewRulesView.vue`
- Create: `frontend/src/views/review/ReviewConsoleView.vue`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: Write failing page integration tests**

Create one spec beside each page. Mount with a real Pinia and memory router, then assert the real landmark and primary action exist. Example for upload:

```ts
it('shows the upload workflow and advances to templates', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ReviewUploadView, { global: { plugins: [pinia, router] } })
  expect(wrapper.get('h1').text()).toBe('上传文档')
  await wrapper.get('[data-test="review-next"]').trigger('click')
  expect(useReviewStore().currentStep).toBe(2)
})
```

The template spec clicks `[data-template-id="services"]` and expects `selectedTemplateId` to equal `services`. The rules spec clicks `[data-clause-id="payment-terms"]` and expects the clause to become disabled. The console spec clicks `[data-test="approve-draft"]` and expects `analysisStatus` to equal `approved`. Each spec also asserts its `h1`: “选择分析范本”, “审查规则与约束配置”, and “AI 审查分析”.

- [ ] **Step 2: Run all four page tests and verify RED**

Run: `npm test -- src/views/review`

Expected: FAIL because the page modules or landmarks do not exist.

- [ ] **Step 3: Implement upload and template pages**

Recreate the source screenshots using Vue templates and scoped CSS: the upload page uses a wide dashed drop zone, stable demo file queue, batch properties, OCR switch, usage meter, and bottom navigation. The template page uses category tabs, search, selectable template cards, and a right document-insight panel. Route navigation calls `review.goToStep()` before `router.push()`.

- [ ] **Step 4: Implement rules and console pages**

The rules page renders grouped typed clauses, configuration summary, sensitivity slider, model and marking selects. The console page uses the three-column desktop layout from `screen.png`: navigation, readable document canvas, and AI risk panel with risk actions and approval controls. Use Chinese demo contract copy and visible “演示分析” labeling.

- [ ] **Step 5: Run page tests and verify GREEN**

Run: `npm test -- src/views/review`

Expected: all review view tests pass.

Run: `npm run build`

Expected: build exits 0.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/review frontend/src/router/index.ts
git commit -m "feat: recreate four-step review prototype"
```

### Task 6: Apply the visual system to existing API-backed pages

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/views/DocsListView.vue`
- Modify: `frontend/src/views/DocPreviewView.vue`
- Modify: `frontend/src/views/HistoryView.vue`
- Modify: `frontend/src/views/FavoritesView.vue`
- Modify: `frontend/src/views/DetailView.vue`
- Modify: `frontend/src/components/ChatInput.vue`
- Modify: `frontend/src/components/ChatMessage.vue`
- Modify: `frontend/src/components/ExampleChips.vue`
- Modify: `frontend/src/components/SessionTable.vue`

- [ ] **Step 1: Add smoke tests for preserved behavior**

Create `frontend/src/views/existing-views.spec.ts`. Mock `@/api/docs`, `@/api/history`, and `@/api/favorites` with resolved empty list responses. Mount `ChatView` and assert `.chat-input-row` exists; mount `DocsListView` and assert `.docs-uploader` and `.docs-table` exist; mount `HistoryView` and assert buttons containing “收藏选中” and “删除选中” exist; mount `FavoritesView` and assert a button containing “删除选中” exists. These assertions lock the existing command surfaces before markup changes.

- [ ] **Step 2: Run smoke tests before markup changes**

Run: `npm test -- src/views`

Expected: existing behavior tests pass before visual refactoring.

- [ ] **Step 3: Refactor page markup and classes**

Replace generic `page-card` framing with unframed page headers, restrained surface panels, consistent toolbars, icon buttons, compact tables, and the shared token vocabulary. Preserve all API calls, event handlers, route names, polling behavior, markdown rendering, upload validation, confirmations, and loading states.

- [ ] **Step 4: Re-run tests and build**

Run: `npm test`

Expected: all tests pass.

Run: `npm run build`

Expected: build exits 0.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views frontend/src/components frontend/src/styles/main.css
git commit -m "style: unify existing pages with review design system"
```

### Task 7: Responsive and visual verification

**Files:**
- Inspect: `frontend/src/styles/main.css`
- Inspect: `frontend/src/components/layout/*.vue`
- Inspect: `frontend/src/views/review/*.vue`
- Test: all files under `frontend/src/**/*.spec.ts`

- [ ] **Step 1: Run the full automated verification**

Run: `npm test`

Expected: all tests pass with 0 failures.

Run: `npm run build`

Expected: build exits 0.

- [ ] **Step 2: Start the development server**

Run: `npm run dev -- --host 127.0.0.1`

Expected: Vite prints a local URL on an unused port.

- [ ] **Step 3: Inspect all primary routes in the in-app browser**

Check `/review/upload`, `/review/templates`, `/review/rules`, `/review/console`, `/`, `/docs`, `/history`, and `/favorites` at 1440x900, 1024x768, and 390x844. Verify no overlap or accidental horizontal page scrolling; long tables may scroll only inside their own region. Confirm all icons render, focus states are visible, and the mobile navigation can open and close.

- [ ] **Step 4: Compare against the four source screenshots**

Verify the shell proportions, spacing rhythm, cool surface hierarchy, blue active states, compact radii, upload composition, template grid, rules summary, document canvas, and risk panel remain faithful to `frontend/review/stitch_/screen.png` and numbered variants.

- [ ] **Step 5: Fix visual findings and re-run verification**

For every behavior defect, add a failing test first. For CSS-only defects, patch the smallest relevant rule, refresh all three viewport sizes, then run `npm test` and `npm run build` again.

- [ ] **Step 6: Commit final verification fixes**

```powershell
git add frontend
git commit -m "fix: harden review prototype responsiveness"
```
