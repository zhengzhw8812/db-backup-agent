import client from './client'

export interface SelfBackupItem {
  name: string
  size: number
  created_at: string
}

export const listSelfBackups = () => client.get<SelfBackupItem[]>('/self-backup')
export const runSelfBackup = () => client.post<{ name: string; size: number }>('/self-backup/run')
export const downloadUrl = (name: string) => `/api/v1/self-backup/${name}/download`
