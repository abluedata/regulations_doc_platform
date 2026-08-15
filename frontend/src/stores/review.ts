import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as reviewApi from '@/api/review'
import { getDoc, uploadDoc } from '@/api/docs'
import type { ReviewClause, ReviewFile, ReviewFileStatus, ReviewRisk, ReviewTemplate, ReviewAnalysisStatus } from '@/types'

type LoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error'

const POLL_INTERVAL_MS = 3000
const RESTORE_WINDOW_MS = 24 * 60 * 60 * 1000

/** 后端文档状态 → 前端展示进度（百分比） */
const STATUS_PROGRESS: Record<string, number> = {
  uploading: 0,
  uploaded: 65,
  queued: 65,
  parsing: 70,
  normalizing: 70,
  needs_ocr: 70,
  chunking: 80,
  indexing: 90,
  ready: 100,
  failed: 0,
}

/** 后端文档状态 → ReviewFile 状态 */
const STATUS_TO_FILE: Record<string, ReviewFileStatus> = {
  uploading: 'uploading',
  uploaded: 'queued',
  queued: 'queued',
  parsing: 'parsing',
  normalizing: 'parsing',
  needs_ocr: 'parsing',
  chunking: 'chunking',
  indexing: 'indexing',
  ready: 'ready',
  failed: 'failed',
}

export const useReviewStore = defineStore('review', () => {
  const currentStep = ref(1)
  const batchId = ref<string | null>(null)
  const selectedTemplateId = ref<string | null>(null)
  const sensitivity = ref(85)
  const markingMode = ref<'standard' | 'high_only'>('standard')
  const analysisProfile = ref<'accurate' | 'fast'>('accurate')
  const analysisStatus = ref<ReviewAnalysisStatus>('idle')
  const analysisJobId = ref<string | null>(null)
  const analysisRevision = ref(0)
  const decisionRevision = ref(0)
  const files = ref<ReviewFile[]>([])
  const templates = ref<ReviewTemplate[]>([])
  const clauses = ref<ReviewClause[]>([])
  const risks = ref<ReviewRisk[]>([])
  const loadState = ref<LoadState>('idle')
  const error = ref('')
  const partialFailure = ref(false)
  const activeFindingId = ref<string | null>(null)
  const restoring = ref(false)
  let restoreAttempted = false
  let streamAbort: AbortController | null = null
  const pollTimers = new Map<string, ReturnType<typeof setInterval>>()
  const pollBusy = new Set<string>()

  const readyCount = computed(() => files.value.filter((file) => file.status === 'ready').length)
  const enabledClauses = computed(() => clauses.value.filter((clause) => clause.enabled))

  function nextStep() { currentStep.value = Math.min(4, currentStep.value + 1) }
  function previousStep() { currentStep.value = Math.max(1, currentStep.value - 1) }
  function goToStep(step: number) {
    if (!Number.isFinite(step)) return
    currentStep.value = Math.min(4, Math.max(1, Math.round(step)))
  }

  async function initialize() {
    if (loadState.value === 'loading') return
    loadState.value = 'loading'
    error.value = ''
    try {
      await Promise.all([loadTemplates(), loadRules()])
      loadState.value = templates.value.length || clauses.value.length ? 'ready' : 'empty'
    } catch (err) {
      error.value = toMessage(err)
      loadState.value = 'error'
    }
  }

  async function loadTemplates() {
    const { data } = await reviewApi.listTemplates()
    templates.value = data.items.map((item) => ({
      id: item.id,
      name: item.name,
      category: item.category,
      description: item.description || '已发布的审查范本。',
      checks: item.rule_version_ids.length,
      icon: 'description',
    }))
    if (!selectedTemplateId.value && templates.value[0]) selectedTemplateId.value = templates.value[0].id
  }

  async function loadRules() {
    const { data } = await reviewApi.listRules()
    clauses.value = data.items.map((item) => ({
      id: item.id,
      group: item.category.toLowerCase().includes('finance') || item.category.includes('财务') ? 'finance' : 'compliance',
      title: item.name,
      description: String(item.definition.description || '已发布的审查规则。'),
      enabled: item.status === 'published',
      priority: item.severity === 'high' ? 'high' : undefined,
      threshold: item.llm_fallback ? 'AI 检查' : '确定性检查',
    }))
  }

  async function createRule(payload: {
    name: string
    category?: string
    severity?: 'low' | 'medium' | 'high'
    definition?: Record<string, unknown>
    llm_fallback?: boolean
  }) {
    const { data } = await reviewApi.createRule(payload)
    await loadRules()
    return data
  }

  async function createTemplate(payload: {
    name: string
    category?: string
    description?: string
    source_version_id?: string
    applicable_document_types?: string[]
    rule_version_ids?: string[]
  }) {
    const sourceVersionId = payload.source_version_id || templates.value[0]?.id || ''
    const { data } = await reviewApi.createTemplate({
      name: payload.name,
      category: payload.category,
      description: payload.description,
      source_version_id: sourceVersionId,
      applicable_document_types: payload.applicable_document_types || [],
      rule_version_ids: payload.rule_version_ids || enabledClauses.value.map((clause) => clause.id),
    })
    await loadTemplates()
    return data
  }

  async function ensureBatch(name: string, documentType: string, ocrRequired: boolean) {
    if (batchId.value) return batchId.value
    const { data } = await reviewApi.createBatch({ name, document_type: documentType, ocr_required: ocrRequired })
    batchId.value = data.id
    return data.id
  }

  async function uploadAndAddFiles(fileList: File[], batchName: string, documentType: string, ocrRequired: boolean) {
    const id = await ensureBatch(batchName, documentType, ocrRequired)
    for (const file of fileList) {
      files.value.push({ id: `upload-${crypto.randomUUID()}`, name: file.name, size: formatSize(file.size), progress: 0, status: 'uploading' })
      // 后续所有变更都通过响应式代理进行，保证模板能感知进度/状态变化
      const local = files.value[files.value.length - 1]!
      try {
        const upload = await uploadDoc(file, (progress) => { local.progress = progress })
        const membership = await reviewApi.addBatchDocument(id, {
          document_id: upload.data.id,
          document_version_id: upload.data.id,
          filename: upload.data.filename,
          status: upload.data.status === 'ready' ? 'ready' : 'queued',
        })
        local.id = membership.data.id
        local.documentId = upload.data.id
        local.documentVersionId = upload.data.id
        local.stageLabel = upload.data.stage_label || ''
        if (upload.data.status === 'ready') {
          local.status = 'ready'
          local.progress = 100
        } else if (upload.data.status === 'failed') {
          local.status = 'failed'
          local.progress = 0
          local.error = upload.data.message || '文档处理失败'
        } else {
          local.status = 'queued'
          local.progress = STATUS_PROGRESS.queued
          // 上传 XHR 结束后后端仍在 parsing/chunking/indexing：轮询真实状态
          startPolling(local)
        }
      } catch (err) {
        local.status = 'failed'
        local.error = toMessage(err)
      }
    }
  }

  /** 把后端文档详情映射到 ReviewFile；返回是否进入终态（ready/failed） */
  function applyDocStatus(file: ReviewFile, doc: { status?: string; stage_label?: string; error?: string | null; file_size?: number | null }) {
    const raw = doc.status || 'queued'
    const mapped = STATUS_TO_FILE[raw] || 'parsing'
    file.status = mapped
    file.progress = STATUS_PROGRESS[raw] ?? file.progress
    file.stageLabel = doc.stage_label || ''
    if (typeof doc.file_size === 'number' && doc.file_size > 0) file.size = formatSize(doc.file_size)
    if (mapped === 'failed') {
      file.progress = 0
      file.error = doc.error || '文档处理失败'
    } else if (mapped === 'ready') {
      file.error = undefined
    }
    return mapped === 'ready' || mapped === 'failed'
  }

  async function pollDocOnce(file: ReviewFile) {
    const documentId = file.documentId
    if (!documentId || pollBusy.has(documentId)) return
    pollBusy.add(documentId)
    try {
      const { data } = await getDoc(documentId)
      const terminal = applyDocStatus(file, data.item)
      if (terminal) stopPolling(documentId)
    } catch {
      // 网络抖动/临时错误：保留现有状态，下一轮重试；404 等永久错误也会在
      // 文档状态变为 failed 后由 applyDocStatus 停止。
    } finally {
      pollBusy.delete(documentId)
    }
  }

  function startPolling(file: ReviewFile) {
    const documentId = file.documentId
    if (!documentId || pollTimers.has(documentId)) return
    void pollDocOnce(file)
    const timer = setInterval(() => { void pollDocOnce(file) }, POLL_INTERVAL_MS)
    pollTimers.set(documentId, timer)
  }

  function stopPolling(documentId: string) {
    const timer = pollTimers.get(documentId)
    if (timer) clearInterval(timer)
    pollTimers.delete(documentId)
  }

  /** 清理所有轮询定时器（组件卸载/页面离开时调用） */
  function dispose() {
    for (const timer of pollTimers.values()) clearInterval(timer)
    pollTimers.clear()
    pollBusy.clear()
  }

  /** 从后端恢复最近 24h 内的批次及其文件（刷新页面后不丢队列） */
  async function restoreFromServer(): Promise<boolean> {
    if (restoreAttempted || files.value.length > 0) return false
    restoreAttempted = true
    restoring.value = true
    try {
      const { data } = await reviewApi.listBatches({ page: 1, page_size: 5 })
      const latest = [...data.items].sort((a, b) => Date.parse(b.created_at || '') - Date.parse(a.created_at || ''))[0]
      if (!latest || !latest.documents?.length) return false
      const ageMs = Date.now() - Date.parse(latest.created_at || '')
      if (!Number.isFinite(ageMs) || ageMs < 0 || ageMs > RESTORE_WINDOW_MS) return false
      batchId.value = latest.id
      for (const member of latest.documents) {
        files.value.push({
          id: member.id,
          name: member.filename,
          size: '',
          progress: STATUS_PROGRESS.queued,
          status: 'queued',
          documentId: member.document_id,
          documentVersionId: member.document_version_id,
        })
        // 通过响应式代理启动轮询，状态刷新会同步到模板
        const tracked = files.value[files.value.length - 1]!
        if (tracked.documentId) startPolling(tracked)
      }
      return true
    } catch {
      return false
    } finally {
      restoring.value = false
    }
  }

  async function removeFile(id: string) {
    const index = files.value.findIndex((item) => item.id === id)
    if (index < 0) return
    const file = files.value[index]
    if (batchId.value && !id.startsWith('upload-')) await reviewApi.removeBatchDocument(batchId.value, id)
    if (file.documentId) stopPolling(file.documentId)
    files.value.splice(index, 1)
  }

  function selectTemplate(id: string) {
    if (templates.value.some((item) => item.id === id)) selectedTemplateId.value = id
  }
  function toggleClause(id: string) {
    const clause = clauses.value.find((item) => item.id === id)
    if (clause && !clause.disabled) clause.enabled = !clause.enabled
  }
  function setSensitivity(value: number) {
    if (Number.isFinite(value)) sensitivity.value = Math.min(100, Math.max(0, Math.round(value)))
  }

  async function startAnalysis() {
    if (!batchId.value) {
      error.value = '请先上传文档并创建批次'
      analysisStatus.value = 'failed'
      throw new Error('尚未创建审查批次，请先在第一步上传文档')
    }
    const memberships = files.value.filter((file) => file.status === 'ready' || file.status === 'queued').map((file) => file.id)
    if (!memberships.length || !enabledClauses.value.length) throw new Error('至少需要一个已就绪文件和一条启用规则')
    analysisStatus.value = 'loading'
    error.value = ''
    try {
      const { data } = await reviewApi.startAnalysis({
        batch_id: batchId.value,
        document_membership_ids: memberships,
        template_version_id: selectedTemplateId.value,
        rule_selections: enabledClauses.value.map((clause) => ({ rule_version_id: clause.id, enabled: true, overrides: {} })),
        sensitivity: sensitivity.value,
        analysis_profile_id: analysisProfile.value,
        marking_mode: markingMode.value,
      }, crypto.randomUUID())
      applyJob(data)
      await loadFindings()
      subscribeAnalysis()
    } catch (err) {
      error.value = toMessage(err)
      analysisStatus.value = 'failed'
      throw err
    }
  }

  function completeAnalysis() { if (analysisStatus.value === 'running' || analysisStatus.value === 'loading') analysisStatus.value = 'complete' }
  function approveDraft() { if (analysisStatus.value === 'complete') analysisStatus.value = 'approved' }
  function rejectChanges() { if (analysisStatus.value === 'complete') analysisStatus.value = 'rejected' }

  async function refreshJob() {
    if (!analysisJobId.value) return
    const { data } = await reviewApi.getAnalysisJob(analysisJobId.value)
    applyJob(data)
    await loadFindings()
  }

  async function loadFindings() {
    if (!analysisJobId.value) return
    const { data } = await reviewApi.listFindings(analysisJobId.value)
    risks.value = data.items.map((item) => ({
      id: item.id,
      level: item.severity,
      section: item.location_label || '原文定位',
      title: item.title,
      description: item.reason,
      currentText: item.quote,
      quote: item.quote,
      referenceText: item.suggestion,
      suggestion: item.suggestion,
      confidence: item.confidence || 'llm_unknown',
      evidence: item.evidence_anchor,
      documentId: item.document_id,
      documentVersionId: item.document_version_id,
      action: item.decision?.decision_type === 'accepted' ? 'accepted' : item.decision?.decision_type === 'dismissed' ? 'dismissed' : 'pending',
    }))
  }

  function subscribeAnalysis() {
    if (!analysisJobId.value) return
    streamAbort?.abort()
    streamAbort = new AbortController()
    void reviewApi.streamAnalysis(analysisJobId.value, {
      onIssues: async () => { await loadFindings() },
      onComplete: async (data) => {
        analysisStatus.value = data.status as ReviewAnalysisStatus
        partialFailure.value = data.status === 'complete_degraded'
        await refreshJob()
      },
      onError: (data) => { error.value = data.message; analysisStatus.value = 'failed' },
    }, streamAbort.signal).catch((err) => {
      if (err.name !== 'AbortError') error.value = toMessage(err)
    })
  }

  async function decideRisk(findingId: string, decision: 'accepted' | 'dismissed', comment: string) {
    if (!analysisJobId.value) return
    await reviewApi.decideFinding(findingId, { decision_type: decision, comment }, decisionRevision.value)
    decisionRevision.value += 1
    await loadFindings()
  }

  async function finalizeDraft(decision: 'approved' | 'rejected', comment = '') {
    if (!analysisJobId.value) return
    await reviewApi.decideOverall(analysisJobId.value, { decision_type: decision, comment }, decisionRevision.value)
    decisionRevision.value += 1
    analysisStatus.value = decision
  }

  async function exportReport() {
    if (!analysisJobId.value) throw new Error('当前没有可导出的审查任务')
    return reviewApi.createExport(analysisJobId.value, crypto.randomUUID())
  }

  function applyJob(job: reviewApi.ReviewJob) {
    analysisJobId.value = job.id
    analysisStatus.value = job.status
    analysisRevision.value = job.result_revision
    decisionRevision.value = job.decision_revision
    partialFailure.value = job.status === 'complete_degraded' || job.documents.some((item) => item.status === 'failed')
  }

  function resetError() { error.value = '' }

  return {
    currentStep, batchId, selectedTemplateId, sensitivity, markingMode, analysisProfile,
    analysisStatus, analysisJobId, analysisRevision, decisionRevision, files, templates, clauses, risks,
    loadState, error, partialFailure, activeFindingId, readyCount, enabledClauses, restoring,
    nextStep, previousStep, goToStep, initialize, loadTemplates, loadRules, createRule, createTemplate, ensureBatch,
    uploadAndAddFiles, removeFile, selectTemplate, toggleClause, setSensitivity, startAnalysis,
    refreshJob, loadFindings, subscribeAnalysis, decideRisk, finalizeDraft, exportReport, resetError,
    completeAnalysis, approveDraft, rejectChanges, restoreFromServer, dispose, applyDocStatus,
  }
})

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function toMessage(error: unknown) {
  return error instanceof Error ? error.message : '审查服务暂时不可用'
}
