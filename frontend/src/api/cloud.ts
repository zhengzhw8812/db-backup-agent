import client from './client'

export interface CloudDestination {
  id: number
  name: string
  provider: string
  endpoint: string
  region: string | null
  bucket: string
  prefix: string
  secure: boolean
  enabled: boolean
  created_at: string
  mounted: boolean | null
  warning?: string | null
  mount_config?: string | null
}
export interface SyncTarget {
  id: number
  connection_id: number
  cloud_destination_id: number
  enabled: boolean
}
export interface BackupFile { id: number; connection_id: number; status: string; file_path: string | null }

export const listDestinations = () => client.get<CloudDestination[]>('/cloud-destinations')
export const createDestination = (data: Record<string, unknown>) => client.post<CloudDestination>('/cloud-destinations', data)
export const updateDestination = (id: number, data: Record<string, unknown>) =>
  client.put<CloudDestination>(`/cloud-destinations/${id}`, data)
/** 保存前测试:用表单临时凭据直连验证(仅 s3) */
export const testDestinationDraft = (data: Record<string, unknown>) =>
  client.post<{ ok: boolean }>('/cloud-destinations/test', data)
export const deleteDestination = (id: number) => client.delete(`/cloud-destinations/${id}`)
export const testDestination = (id: number) => client.post(`/cloud-destinations/${id}/test`)
export const listTargets = () => client.get<SyncTarget[]>('/sync-targets')
export const createTarget = (data: Record<string, unknown>) => client.post<SyncTarget>('/sync-targets', data)
export const deleteTarget = (id: number) => client.delete(`/sync-targets/${id}`)
export const syncRun = (backup_record_id: number) => client.post('/sync/run', { backup_record_id })
