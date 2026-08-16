import http from '../http'
import type { ListResponse, SessionRecord } from '@/types'

export function listHistory(params?: {
  id?: string
  q?: string
  date_start?: string
  date_end?: string
  page?: number
  page_size?: number
}) {
  return http.get<ListResponse<SessionRecord>>('/history', { params })
}

export function getHistoryDetail(id: string) {
  return http.get<SessionRecord>(`/history/${encodeURIComponent(id)}`)
}

export function deleteHistory(id: string) {
  return http.delete(`/history/${encodeURIComponent(id)}`)
}

export function clearHistory() {
  return http.delete('/history')
}

export function batchDeleteHistory(ids: string[]) {
  return http.post<{ ok: number; message: string }>('/history/batch-delete', { ids })
}

export function batchFavoriteHistory(ids: string[]) {
  return http.post<{ ok: number; message: string }>('/history/batch-favorite', { ids })
}
