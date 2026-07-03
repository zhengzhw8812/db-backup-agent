import client from './client'

export interface Restore {
  id: number
  backup_record_id: number
  target_connection_id: number
  status: string
  error: string | null
  started_at: string
  finished_at: string | null
  duration_ms: number | null
}

export const runRestore = (backup_record_id: number, target_connection_id: number) =>
  client.post<{ record_id: number; status: string }>('/restore', { backup_record_id, target_connection_id })
export const listRestores = () => client.get<Restore[]>('/restore')
export const cancelRestore = (id: number) => client.post(`/restore/${id}/cancel`)
export const eventsUrl = (id: number) => `/api/v1/restore/${id}/events`
