import http from './http'

export interface ReviewPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ReviewRule {
  id: string
  rule_id: string
  name: string
  category: string
  severity: 'low' | 'medium' | 'high'
  definition: Record<string, unknown>
  status: string
  llm_fallback?: boolean
}

export interface ReviewTemplateVersion {
  id: string
  name: string
  category: string
  description: string
  rule_version_ids: string[]
  status: string
}

export interface ReviewBatchDocument {
  id: string
  document_id: string
  document_version_id: string
  filename: string
  status: string
  ir?: Record<string, unknown>
  created_at?: string
}

export interface ReviewBatch {
  id: string
  name: string
  document_type: string
  ocr_required: boolean
  revision: number
  documents: ReviewBatchDocument[]
  created_at?: string
  updated_at?: string
}

export interface ReviewFinding {
  id: string
  title: string
  severity: 'low' | 'medium' | 'high'
  reason: string
  suggestion: string
  quote: string
  location_label: string
  confidence?: string
  document_id?: string
  document_version_id?: string
  evidence_anchor: Record<string, any>
  decision?: { decision_type: string; comment?: string | null } | null
}

export interface ReviewJob {
  id: string
  status: 'queued' | 'parsing' | 'running' | 'complete' | 'complete_degraded' | 'failed' | 'cancelled'
  progress: number
  revision: number
  result_revision: number
  decision_revision: number
  snapshot: {
    template_version_id?: string | null
    rule_version_ids?: string[]
    version_tuple?: Record<string, unknown>
  }
  documents: Array<{ id: string; document_id: string; document_version_id: string; status: string; progress: number; error?: unknown }>
  error?: { code?: string; message?: string } | null
}

export interface StreamHandlers {
  onIssues?: (issues: ReviewFinding[]) => void
  onComplete?: (data: { status: string; finding_count?: number }) => void
  onError?: (data: { message: string }) => void
}

export function listRules(params?: Record<string, unknown>) {
  return http.get<ReviewPage<ReviewRule>>('/review/rules', { params })
}

export function listTemplates(params?: Record<string, unknown>) {
  return http.get<ReviewPage<ReviewTemplateVersion>>('/review/templates', { params })
}

export function createRule(payload: {
  name: string
  category?: string
  severity?: 'low' | 'medium' | 'high'
  definition?: Record<string, unknown>
  source_anchor?: Record<string, unknown> | null
  configurable_fields?: string[]
  llm_fallback?: boolean
}) {
  return http.post<ReviewRule>('/review/rules', payload)
}

export function createTemplate(payload: {
  template_id?: string | null
  name: string
  category?: string
  description?: string
  source_version_id: string
  applicable_document_types: string[]
  rule_version_ids?: string[]
}) {
  return http.post<ReviewTemplateVersion>('/review/templates', payload)
}

export function createBatch(payload: { name: string; document_type: string; ocr_required: boolean }) {
  return http.post<ReviewBatch>('/review/batches', payload)
}

export function getBatch(batchId: string) {
  return http.get<ReviewBatch>(`/review/batches/${batchId}`)
}

export function listBatches(params?: { page?: number; page_size?: number }) {
  return http.get<ReviewPage<ReviewBatch>>('/review/batches', { params })
}

export function addBatchDocument(batchId: string, payload: Omit<ReviewBatchDocument, 'id'>) {
  return http.post<ReviewBatchDocument>(`/review/batches/${batchId}/documents`, payload)
}

export function removeBatchDocument(batchId: string, membershipId: string) {
  return http.delete(`/review/batches/${batchId}/documents/${membershipId}`)
}

export function startAnalysis(payload: {
  batch_id: string
  document_membership_ids: string[]
  template_version_id?: string | null
  rule_selections: Array<{ rule_version_id: string; enabled: boolean; overrides: Record<string, unknown> }>
  sensitivity: number
  analysis_profile_id: 'accurate' | 'fast'
  marking_mode: 'standard' | 'high_only'
}, idempotencyKey: string) {
  return http.post<ReviewJob>('/review/analysis-jobs', payload, { headers: { 'Idempotency-Key': idempotencyKey } })
}

export function getAnalysisJob(jobId: string) {
  return http.get<ReviewJob>(`/review/analysis-jobs/${jobId}`)
}

export function listFindings(jobId: string, params?: Record<string, unknown>) {
  return http.get<ReviewPage<ReviewFinding> & { result_revision: number; counts: Record<string, number> }>(
    `/review/analysis-jobs/${jobId}/findings`,
    { params },
  )
}

export function decideFinding(findingId: string, payload: { decision_type: string; comment?: string }, revision: number) {
  return http.put(`/review/findings/${findingId}/decision`, payload, { headers: { 'If-Match': String(revision) } })
}

export function decideOverall(jobId: string, payload: { decision_type: string; comment?: string }, revision: number) {
  return http.put(`/review/analysis-jobs/${jobId}/decision`, payload, { headers: { 'If-Match': String(revision) } })
}

export function startHitlDecision(payload: { analysis_job_id: string; finding_id?: string; decision_type: string; comment?: string }) {
  return http.post('/review/decisions/start', payload)
}

export function resumeHitlDecision(id: string, payload: { action: 'confirm' | 'cancel'; comment?: string }) {
  return http.post(`/review/decisions/${id}/resume`, payload)
}

export function createExport(jobId: string, idempotencyKey: string) {
  return http.post(`/review/analysis-jobs/${jobId}/exports`, { format: 'markdown' }, { headers: { 'Idempotency-Key': idempotencyKey } })
}

export async function downloadExportArtifact(artifactId: string, filename = 'review-report.md') {
  const res = await http.get<Blob>(`/review/export-artifacts/${artifactId}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(res.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export interface ReviewCitation {
  citation_id: string
  document_id: string
  document_version_id: string
  filename: string
  block_id: string
  chunk_id?: number | null
  section_path?: string[]
  quote: string
  quote_start: number
  quote_end: number
  locator: Record<string, unknown>
}

export function createConversation(analysisJobId: string, documentMembershipId: string) {
  return http.post<{ id: string; document_id: string; document_version_id: string }>('/review/conversations', {
    analysis_job_id: analysisJobId,
    document_membership_id: documentMembershipId,
  })
}

export function stopConversation(conversationId: string, requestId: string) {
  return http.post(`/review/conversations/${conversationId}/stop`, { request_id: requestId })
}

export async function streamAnalysis(jobId: string, handlers: StreamHandlers, signal?: AbortSignal) {
  const base = import.meta.env.VITE_API_BASE || '/api'
  const response = await fetch(`${base}/review/analysis-jobs/${jobId}/stream`, { headers: { Accept: 'text/event-stream' }, signal })
  if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
  await consumeSse(response.body, (event, data) => {
    if (event === 'issues') handlers.onIssues?.(data)
    if (event === 'complete') handlers.onComplete?.(data)
    if (event === 'error') handlers.onError?.(data)
  })
}

export async function streamReviewAssistant(
  conversationId: string,
  payload: { request_id: string; message: string; finding_id?: string; history: Array<{ role: string; content: string }> },
  handlers: {
    onMeta?: (data: Record<string, unknown>) => void
    onStatus?: (data: { request_id: string; type: 'retrieving' | 'generating' }) => void
    onToken?: (data: { request_id: string; content: string }) => void
    onDone?: (data: { request_id: string; answer: string; refused: boolean; refusal_code?: string; citations: ReviewCitation[] }) => void
    onError?: (data: { request_id: string; code: string; message: string; retryable: boolean }) => void
  },
  signal?: AbortSignal,
) {
  const base = import.meta.env.VITE_API_BASE || '/api'
  const response = await fetch(`${base}/review/conversations/${conversationId}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
  let terminal = false
  await consumeSse(response.body, (event, data) => {
    if (terminal) return
    if (event === 'meta') handlers.onMeta?.(data)
    else if (event === 'status') handlers.onStatus?.(data)
    else if (event === 'token') handlers.onToken?.(data)
    else if (event === 'done') { terminal = true; handlers.onDone?.(data) }
    else if (event === 'error') { terminal = true; handlers.onError?.(data) }
  })
}

async function consumeSse(body: ReadableStream<Uint8Array>, onEvent: (event: string, data: any) => void) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      let event = 'message'
      const lines: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) lines.push(line.slice(5).trim())
      }
      if (!lines.length) continue
      try { onEvent(event, JSON.parse(lines.join('\n'))) } catch { onEvent(event, { message: lines.join('\n') }) }
    }
  }
}
