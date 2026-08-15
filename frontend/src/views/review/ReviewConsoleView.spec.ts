import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewConsoleView from './ReviewConsoleView.vue'
import { useReviewStore } from '@/stores/review'
import type { ReviewAnalysisStatus } from '@/types'

vi.mock('@/api/review', () => ({
  listRules: vi.fn(),
  listTemplates: vi.fn(),
  createRule: vi.fn(),
  createTemplate: vi.fn(),
  createBatch: vi.fn(),
  addBatchDocument: vi.fn(),
  removeBatchDocument: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysisJob: vi.fn(),
  listFindings: vi.fn(),
  streamAnalysis: vi.fn(),
  decideFinding: vi.fn(),
  decideOverall: vi.fn(),
  createExport: vi.fn(),
  downloadExportArtifact: vi.fn(),
}))

vi.mock('@/api/docs', () => ({
  uploadDoc: vi.fn(),
}))

import * as reviewApi from '@/api/review'

const evidenceAnchor = {
  kind: 'pdf',
  document_id: 'doc-1',
  document_version_id: 'version-1',
  precision: 'exact',
  quote: 'liability limited to $5,000,000',
  page_number: 4,
  coordinate_space: 'normalized-1000-top-left',
  rects: [{ x0: 120, y0: 318, x1: 635, y1: 354 }],
  block_ids: ['p4-b12'],
}

const finding = {
  id: 'f1',
  title: '责任限制过高',
  severity: 'high',
  reason: '责任上限为固定金额，缺少按合同额比例的约定。',
  suggestion: '建议改为按合同额的合理比例或设置上限。',
  quote: 'liability limited to $5,000,000',
  location_label: '第 3 节 责任限制',
  confidence: 'high',
  evidence_anchor: evidenceAnchor,
  decision: null,
}

function jobPayload(status: string) {
  return { id: 'job-1', status, progress: 100, revision: 0, result_revision: 0, decision_revision: 0, snapshot: {}, documents: [] }
}

function setupJobStore(options: { status?: ReviewAnalysisStatus; findings?: Array<typeof finding> } = {}) {
  const store = useReviewStore()
  store.analysisJobId = 'job-1'
  store.analysisStatus = options.status ?? 'complete'
  vi.mocked(reviewApi.getAnalysisJob).mockResolvedValue({ data: jobPayload(options.status ?? 'complete') } as never)
  vi.mocked(reviewApi.listFindings).mockResolvedValue({
    data: { items: options.findings ?? [], total: (options.findings ?? []).length, page: 1, page_size: 50, result_revision: 0, counts: {} },
  } as never)
  return store
}

async function mountConsole() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/review/upload', name: 'review-upload', component: { template: '<div>upload</div>' } },
      { path: '/review/rules', name: 'review-rules', component: { template: '<div>rules</div>' } },
      { path: '/review/console', name: 'review-console', component: ReviewConsoleView },
    ],
  })
  await router.push('/review/console')
  await router.isReady()
  const wrapper = mount(ReviewConsoleView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

describe('ReviewConsoleView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(reviewApi.streamAnalysis).mockResolvedValue(undefined as never)
    vi.mocked(reviewApi.downloadExportArtifact).mockResolvedValue(undefined as never)
  })

  it('loads real findings from the backend for an existing analysis job', async () => {
    setupJobStore({ findings: [finding] })
    const { wrapper } = await mountConsole()

    expect(reviewApi.getAnalysisJob).toHaveBeenCalledWith('job-1')
    expect(reviewApi.listFindings).toHaveBeenCalledWith('job-1')
    expect(wrapper.get('h1').text()).toBe('AI 审查分析')
    expect(wrapper.find('.risk-card').exists()).toBe(true)
    expect(wrapper.find('.risk-card__title').text()).toBe('责任限制过高')
  })

  it('approves a completed analysis', async () => {
    const store = setupJobStore({ findings: [finding] })
    const { wrapper } = await mountConsole()

    await wrapper.get('[data-test="approve-draft"]').trigger('click')

    expect(store.analysisStatus).toBe('approved')
  })

  it('disables approval while the analysis is running', async () => {
    setupJobStore({ status: 'running', findings: [] })
    const { wrapper } = await mountConsole()

    expect(wrapper.get('[data-test="approve-draft"]').attributes('disabled')).toBeDefined()
  })

  it('renders a loaded console without an internal left navigation panel', async () => {
    setupJobStore({ findings: [finding] })
    const { wrapper } = await mountConsole()

    expect(wrapper.find('.document-outline').exists()).toBe(false)
    expect(wrapper.find('.reader-panel').exists()).toBe(true)
    expect(wrapper.find('.findings-panel').exists()).toBe(true)
  })

  it('shows the empty findings state when there are no results', async () => {
    setupJobStore({ findings: [] })
    const { wrapper } = await mountConsole()

    expect(wrapper.find('.risk-card').exists()).toBe(false)
    expect(wrapper.find('.findings-empty').text()).toBe('暂无审查发现')
  })

  it('switches the analysis panel to the question assistant tab', async () => {
    setupJobStore({ findings: [finding] })
    const { wrapper } = await mountConsole()

    expect(wrapper.find('.review-assistant').exists()).toBe(false)

    await wrapper.get('[data-test="assistant-tab"]').trigger('click')

    expect(wrapper.find('.review-assistant').exists()).toBe(true)
    expect(wrapper.find('.findings-content').exists()).toBe(false)
  })

  it('guides the user back to upload when no analysis job exists', async () => {
    const { wrapper, router } = await mountConsole()

    expect(wrapper.find('.console-empty').exists()).toBe(true)
    expect(wrapper.find('.reader-panel').exists()).toBe(false)

    await wrapper.get('[data-test="back-to-upload"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('review-upload')
  })

  it('dispatches review:locate-evidence with the evidence anchor when a risk is selected', async () => {
    setupJobStore({ findings: [finding] })
    const { wrapper } = await mountConsole()

    const events: CustomEvent[] = []
    window.addEventListener('review:locate-evidence', (event) => events.push(event as CustomEvent))

    await wrapper.get('.risk-card').trigger('click')

    expect(events).toHaveLength(1)
    expect(events[0].detail).toEqual(evidenceAnchor)
  })

  it('exports the report through the store and triggers a download', async () => {
    setupJobStore({ findings: [finding] })
    vi.mocked(reviewApi.createExport).mockResolvedValue({
      data: { id: 'exp-1', filename: 'review-job-1.md' },
    } as never)
    const { wrapper } = await mountConsole()

    await wrapper.get('[data-test="export-report"]').trigger('click')
    await flushPromises()

    expect(reviewApi.createExport).toHaveBeenCalledWith('job-1', expect.any(String))
    expect(reviewApi.downloadExportArtifact).toHaveBeenCalledWith('exp-1', 'review-job-1.md')
  })
})
