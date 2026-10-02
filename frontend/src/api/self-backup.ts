import client from './client'

export interface SelfBackupItem {
  name: string
  kind: 'gz' | 'sql'
  size: number
  created_at: string
}

export const listSelfBackups = () => client.get<SelfBackupItem[]>('/self-backup')
export const runSelfBackup = (fmt: 'gz' | 'sql' = 'gz') =>
  client.post<{ name: string; size: number; kind: string }>(`/self-backup/run?fmt=${fmt}`)
export const downloadUrl = (name: string) => `/api/v1/self-backup/${name}/download`
export const importSql = (fd: FormData) => client.post<{ staged: boolean; message: string }>('/self-backup/import', fd)
export const restoreListed = (name: string) => client.post<{ staged: boolean; message: string }>(`/self-backup/${name}/restore`)
