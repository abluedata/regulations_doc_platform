import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReviewStore } from './review'

vi.mock('@/api/review/review', () => ({
  listRules: vi.fn(),
  listTemplates: vi.fn(),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  createTemplate: vi.fn(),
  createBatch: vi.fn(),
  addBatchDocument: vi.fn(),
  removeBatchDocument: vi.fn(),
  startAnalysis: vi.fn(),
  getAnalysisJob: vi.fn(),
  listFindings: vi.fn(),
  streamAnalysis: vi.fn(() => Promise.resolve()),
  decideFinding: vi.fn(),
  decideOverall: vi.fn(),
  createExport: vi.fn(),
  listConfigurations: vi.fn(),
  createConfiguration: vi.fn(),
  listBatches: vi.fn(),
  getBatch: vi.fn(),
}))

vi.mock('@/api/knowledge/docs', () => ({
  uploadDoc: vi.fn(),
}))

import * as reviewApi from '@/api/review/review'
import * as docsApi from '@/api/knowledge/docs'

describe('review store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts with empty collections instead of demo data', () => {
    const store = useReviewStore()

    expect(store.files).toEqual([])
    expect(store.templates).toEqual([])
    expect(store.clauses).toEqual([])
    expect(store.selectedTemplateId).toBeNull()
    expect(store.batchId).toBeNull()
  })

  it('moves through the four review steps without exceeding the bounds', () => {
    const store = useReviewStore()

    expect(store.currentStep).toBe(1)
    store.nextStep()
    store.nextStep()
    store.nextStep()
    store.nextStep()
    expect(store.currentStep).toBe(4)

    store.previousStep()
    store.previousStep()
    store.previousStep()
    store.previousStep()
    expect(store.currentStep).toBe(1)

    store.goToStep(99)
    expect(store.currentStep).toBe(4)
    store.goToStep(-2)
    expect(store.currentStep).toBe(1)
    store.goToStep(2.5)
    expect(store.currentStep).toBe(3)
    store.goToStep(Number.NaN)
    expect(store.currentStep).toBe(3)
  })

  it('clamps sensitivity to the supported percentage range', () => {
    const store = useReviewStore()

    store.setSensitivity(-10)
    expect(store.sensitivity).toBe(0)

    store.setSensitivity(105)
    expect(store.sensitivity).toBe(100)

    store.setSensitivity(72.5)
    expect(store.sensitivity).toBe(73)
    store.setSensitivity(Number.NaN)
    expect(store.sensitivity).toBe(73)
  })

  it('rejects an analysis attempt when no batch exists', async () => {
    const store = useReviewStore()

    await expect(store.startAnalysis()).rejects.toThrow('尚未创建审查批次')
    expect(store.analysisStatus).toBe('failed')
    expect(reviewApi.startAnalysis).not.toHaveBeenCalled()
  })

  it('loads templates and rules from the backend on initialize', async () => {
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({
      data: { items: [{ id: 'tpl-1', name: 'Mutual NDA', category: '交易类', description: 'desc', rule_version_ids: ['r1', 'r2'], status: 'published' }], total: 1, page: 1, page_size: 50 },
    } as never)
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: { items: [{ id: 'r1', rule_id: 'r1', name: '付款条款', category: 'finance', severity: 'medium', definition: { description: '付款检查' }, status: 'published' }], total: 1, page: 1, page_size: 50 },
    } as never)

    const store = useReviewStore()
    await store.initialize()

    expect(store.templates).toHaveLength(1)
    expect(store.clauses).toHaveLength(1)
    expect(store.selectedTemplateId).toBe('tpl-1')
    expect(store.loadState).toBe('ready')
  })

  it('creates a rule through the backend and reloads the list', async () => {
    vi.mocked(reviewApi.createRule).mockResolvedValue({
      data: { id: 'r9', rule_id: 'r9', name: '履约保函', category: 'compliance', severity: 'high', definition: {}, status: 'published' },
    } as never)
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: { items: [{ id: 'r9', rule_id: 'r9', name: '履约保函', category: 'compliance', severity: 'high', definition: { description: '检查保函' }, status: 'published' }], total: 1, page: 1, page_size: 50 },
    } as never)

    const store = useReviewStore()
    await store.createRule({ name: '履约保函', category: 'compliance', severity: 'high' })

    expect(reviewApi.createRule).toHaveBeenCalledWith(expect.objectContaining({ name: '履约保函' }))
    expect(store.clauses.map((c) => c.title)).toContain('履约保函')
  })

  it('sends latest rule selections without configuration id after user toggles', async () => {
    const rules = [
      { id: 'r1', rule_id: 'r1', name: '规则A', category: '财务', severity: 'medium', definition: { description: '描述A' }, status: 'published', version: 1 },
      { id: 'r2', rule_id: 'r2', name: '规则B', category: '合规', severity: 'high', definition: { description: '描述B' }, status: 'published', version: 1 },
    ]
    vi.mocked(reviewApi.listRules).mockResolvedValue({ data: { items: rules }, total: 2, page: 1, page_size: 50 } as never)
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({ data: { items: [] }, total: 0, page: 1, page_size: 50 } as never)
    vi.mocked(reviewApi.listConfigurations).mockResolvedValue({
      data: {
        items: [{
          id: 'cfg-1', name: '默认配置',
          rule_selections: [
            { rule_version_id: 'r1', enabled: true, overrides: {} },
            { rule_version_id: 'r2', enabled: true, overrides: {} },
          ],
          sensitivity: 80, analysis_profile_id: 'accurate', marking_mode: 'standard', revision: 0,
        }],
        total: 1, page: 1, page_size: 50,
      },
    } as never)
    vi.mocked(reviewApi.startAnalysis).mockResolvedValue({
      data: {
        id: 'job-1', status: 'complete', progress: 100, revision: 0, result_revision: 0, decision_revision: 0,
        snapshot: {}, documents: [],
      },
    } as never)
    vi.mocked(reviewApi.listFindings).mockResolvedValue({ data: { items: [] } } as never)

    const store = useReviewStore()
    await store.initialize()
    store.batchId = 'b1'
    store.files = [{ id: 'm1', name: 'a.pdf', size: '1 KB', progress: 100, status: 'ready', documentId: 'd1', documentVersionId: 'v1' }]

    // 未修改：复用已保存配置
    await store.startAnalysis()
    expect(vi.mocked(reviewApi.startAnalysis).mock.calls[0]?.[0].configuration_id).toBe('cfg-1')

    // 用户停用规则B：以最新选择为准，不再携带配置 ID
    store.toggleClause('r2')
    expect(store.configurationDirty).toBe(true)
    await store.startAnalysis()
    const latest = vi.mocked(reviewApi.startAnalysis).mock.calls.at(-1)?.[0]
    expect(latest?.configuration_id).toBeNull()
    expect(latest?.rule_selections).toEqual([{ rule_version_id: 'r1', enabled: true, overrides: {} }])
  })

  it('creates a template through the backend and reloads the list', async () => {
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: { items: [{ id: 'r1', rule_id: 'r1', name: '付款条款', category: 'finance', severity: 'medium', definition: {}, status: 'published' }], total: 1, page: 1, page_size: 50 },
    } as never)
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({
      data: { items: [{ id: 'tpl-x', name: '自定义范本', category: '交易类', description: 'desc', rule_version_ids: ['r1'], status: 'draft' }], total: 1, page: 1, page_size: 50 },
    } as never)
    vi.mocked(reviewApi.createTemplate).mockResolvedValue({
      data: { id: 'tpl-x', name: '自定义范本', category: '交易类', description: 'desc', rule_version_ids: ['r1'], status: 'draft' },
    } as never)

    const store = useReviewStore()
    await store.initialize()
    await store.createTemplate({ name: '自定义范本', category: '交易类' })

    expect(reviewApi.createTemplate).toHaveBeenCalledWith(expect.objectContaining({ name: '自定义范本' }))
    expect(store.templates.map((t) => t.name)).toContain('自定义范本')
  })

  it('selectTemplate only accepts a template that exists in the loaded collection', async () => {
    vi.mocked(reviewApi.listTemplates).mockResolvedValue({
      data: { items: [{ id: 'tpl-1', name: 'A', category: '交易类', description: 'd', rule_version_ids: [], status: 'published' }], total: 1, page: 1, page_size: 50 },
    } as never)
    vi.mocked(reviewApi.listRules).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
    } as never)

    const store = useReviewStore()
    await store.initialize()

    store.selectTemplate('unknown-template')
    expect(store.selectedTemplateId).toBe('tpl-1')

    store.selectTemplate('tpl-1')
    expect(store.selectedTemplateId).toBe('tpl-1')
  })

  it('keeps approval actions inert outside the complete state', () => {
    const store = useReviewStore()

    store.completeAnalysis()
    store.approveDraft()
    store.rejectChanges()

    expect(store.analysisStatus).toBe('idle')
  })

  it('runs the analysis and completes via the real lifecycle when a batch exists', async () => {
    const store = useReviewStore()
    store.batchId = 'batch-1'
    store.files.push({ id: 'mem-1', name: 'a.pdf', size: '1 KB', progress: 100, status: 'ready' })
    store.clauses.push({ id: 'r1', group: 'finance', title: '付款', description: 'x', enabled: true })

    vi.mocked(reviewApi.startAnalysis).mockResolvedValue({
      data: { id: 'job-1', status: 'running', progress: 0, revision: 0, result_revision: 0, decision_revision: 0, snapshot: {}, documents: [] },
    } as never)
    vi.mocked(reviewApi.listFindings).mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50, result_revision: 0, counts: {} },
    } as never)
    vi.mocked(reviewApi.streamAnalysis).mockResolvedValue(undefined as never)

    await store.startAnalysis()
    expect(reviewApi.startAnalysis).toHaveBeenCalled()
    expect(store.analysisStatus).toBe('running')

    store.completeAnalysis()
    expect(store.analysisStatus).toBe('complete')
    store.approveDraft()
    expect(store.analysisStatus).toBe('approved')
  })

  it('lists files added through the real upload and batch membership flow', async () => {
    const store = useReviewStore()
    vi.mocked(reviewApi.createBatch).mockResolvedValue({
      data: { id: 'batch-1', name: 'b', document_type: '商业合同', ocr_required: false, revision: 0, documents: [] },
    } as never)
    vi.mocked(docsApi.uploadDoc).mockResolvedValue({
      data: { id: 'doc-1', filename: 'tender_file.pdf', status: 'ready', stage_label: 'ready', message: '' },
    } as never)
    vi.mocked(reviewApi.addBatchDocument).mockResolvedValue({
      data: { id: 'mem-1', document_id: 'doc-1', document_version_id: 'doc-1', filename: 'tender_file.pdf', status: 'ready' },
    } as never)

    const file = new File(['pdf'], 'tender_file.pdf', { type: 'application/pdf' })
    await store.uploadAndAddFiles([file], 'batch', '商业合同', false)

    expect(reviewApi.createBatch).toHaveBeenCalled()
    expect(docsApi.uploadDoc).toHaveBeenCalled()
    expect(reviewApi.addBatchDocument).toHaveBeenCalled()
    expect(store.files).toHaveLength(1)
    expect(store.files[0].name).toBe('tender_file.pdf')
    expect(store.files[0].status).toBe('ready')
    expect(store.batchId).toBe('batch-1')
  })
})
