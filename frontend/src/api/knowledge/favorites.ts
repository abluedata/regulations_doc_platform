import http from '../http'
import type { ListResponse, SessionRecord } from '@/types'

export function listFavorites(params?: { page?: number; page_size?: number }) {
  return http.get<ListResponse<SessionRecord>>('/favorites', { params })
}

export function addFavorite(id: string) {
  return http.post(`/favorites/${encodeURIComponent(id)}`)
}

export function removeFavorite(id: string) {
  return http.delete(`/favorites/${encodeURIComponent(id)}`)
}

export function batchDeleteFavorites(ids: string[]) {
  return http.post<{ ok: number; message: string }>('/favorites/batch-delete', { ids })
}
