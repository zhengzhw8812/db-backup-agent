import client from './client'

export interface SystemLog {
  id: number
  level: string
  source: string
  message: string
  context: string | null
  created_at: string
}

export const listLogs = (level?: string) =>
  client.get<SystemLog[]>('/logs', { params: level ? { level } : {} })
