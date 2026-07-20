export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface SessionRecord {
  id: string
  timestamp: string
  question: string
  answer: string
  route?: string
  has_web?: boolean
  messages?: ChatMessage[]
}

export interface ListResponse<T> {
  items: T[]
  total: number
}

/** 知识库文档 */
export type DocStatus =
  | 'uploaded'
  | 'queued'
  | 'parsing'
  | 'normalizing'
  | 'chunking'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'needs_ocr'
  | string

export interface DocRecord {
  id: string
  filename: string
  title?: string
  ext?: string
  status: DocStatus
  stage_label?: string
  error?: string | null
  page_count?: number | null
  chunk_count?: number | null
  file_size?: number | null
  created_at?: string
  updated_at?: string
  duration_sec?: number | null
  engine?: string | null
  mime?: string
  stored_name?: string
}

export interface DocOutlineItem {
  block_id: string
  text: string
  level: number
  section_path?: string[]
}

export interface DocTableItem {
  block_id: string
  section_path?: string[]
  page_start?: number | null
  page_end?: number | null
  merged?: boolean
  html: string
  markdown: string
}

export interface DocPreview {
  id: string
  status: DocStatus
  stage_label?: string
  ready: boolean
  message?: string | null
  markdown: string
  outline: DocOutlineItem[]
  tables: DocTableItem[]
  meta: DocRecord
  ir_summary?: {
    block_count?: number
    title?: string
    pages?: number | null
  }
}

export type ReviewAnalysisStatus = 'idle' | 'running' | 'complete' | 'approved' | 'rejected'

export interface ReviewFile {
  id: string
  name: string
  size: string
  progress: number
  status: 'ready' | 'uploading' | 'queued'
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
}

export interface ReviewRisk {
  id: string
  level: 'high' | 'medium' | 'low'
  section: string
  title: string
  description: string
  currentText?: string
  referenceText?: string
}
