export type ReviewAnalysisStatus = 'idle' | 'loading' | 'queued' | 'parsing' | 'running' | 'complete' | 'complete_degraded' | 'failed' | 'cancelled' | 'approved' | 'rejected'

export type ReviewFileStatus = 'uploading' | 'queued' | 'parsing' | 'chunking' | 'indexing' | 'ready' | 'failed'

export interface ReviewFile {
  id: string
  name: string
  size: string
  progress: number
  status: ReviewFileStatus
  stageLabel?: string
  error?: string
  documentId?: string
  documentVersionId?: string
}

export interface ReviewTemplate {
  id: string
  name: string
  category: string
  description: string
  checks: number
  icon: string
  popular?: boolean
}

export interface ReviewClause {
  id: string
  group: 'finance' | 'compliance'
  title: string
  description: string
  enabled: boolean
  priority?: 'high'
  threshold?: string
  disabled?: boolean
  category?: string
  severity?: 'low' | 'medium' | 'high'
  version?: number
}

export interface ReviewRisk {
  id: string
  level: 'high' | 'medium' | 'low'
  section: string
  title: string
  description: string
  currentText?: string
  referenceText?: string
  quote?: string
  suggestion?: string
  confidence?: string
  evidence?: Record<string, unknown>
  documentId?: string
  documentVersionId?: string
  action?: 'pending' | 'accepted' | 'dismissed'
}

/** PDF 证据高亮矩形（见 ReviewPdfPreview 组件） */
export interface ReviewHighlightRect {
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
  /** pdf-pt（默认，PDF 页点坐标，原点左上）或 normalized-1000-top-left */
  space?: string
  /** true 表示页级定位（precision=page），渲染为页顶横条 + 角标 */
  pageLevel?: boolean
}
