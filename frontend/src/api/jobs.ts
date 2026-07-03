import client from './client'

export interface Job {
  id: number
  connection_id: number
  trigger: string
  status: string
  error: string | null
  started_at: string
  finished_at: string | null
}

export const runBackup = (connection_id: number) =>
  client.post<{ record_id: number; status: string }>('/backups/run', { connection_id })
export const listJobs = () => client.get<Job[]>('/jobs')
export const cancelJob = (id: number) => client.post(`/jobs/${id}/cancel`)
