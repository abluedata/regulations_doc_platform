import http from '../http'
import type { DocPreview, DocRecord, ListResponse } from '@/types'

export function listDocs(params?: {
  q?: string
  status?: string
  page?: number
  page_size?: number
}) {
  return http.get<ListResponse<DocRecord>>('/docs', { params })
}

export function getDoc(id: string) {
  return http.get<{ item: DocRecord }>(`/docs/${id}`)
}

export function getDocPreview(id: string) {
  return http.get<DocPreview>(`/docs/${id}/preview`)
}

export function deleteDoc(id: string) {
  return http.delete<{ message: string; success: boolean }>(`/docs/${id}`)
}

export function reparseDoc(id: string) {
  return http.post<{ message: string; success: boolean }>(`/docs/${id}/reparse`)
}

export function uploadDoc(file: File, onProgress?: (pct: number) => void) {
  const form = new FormData()
  form.append('file', file)
  return http.post<{
    id: string
    filename: string
    status: string
    stage_label: string
    message: string
  }>('/docs/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
    onUploadProgress: (e) => {
      if (!onProgress || !e.total) return
      onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}
