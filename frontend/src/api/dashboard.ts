import client from './client'

export interface DashboardStats {
  total: number
  success: number
  failed: number
  success_rate: number
  storage_bytes: number
  running: number
}

export interface DashboardTrends {
  daily: { date: string; success: number; failed: number }[]
  by_type: { type: string; storage_bytes: number }[]
}

export const getStats = () => client.get<DashboardStats>('/dashboard/stats')
export const getTrends = () => client.get<DashboardTrends>('/dashboard/trends')
