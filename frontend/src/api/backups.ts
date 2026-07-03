import client from './client'

export interface BackupFile {
  id: number
  connection_id: number
  status: string
  file_path: string | null
  size: number | null
  checksum: string | null
  duration_ms: number | null
  started_at: string
  finished_at: string | null
}

export const listBackups = () => client.get<BackupFile[]>('/backups')
export const deleteBackup = (id: number) => client.delete(`/backups/${id}`)
export const downloadUrl = (id: number) => `/api/v1/backups/${id}/download`
