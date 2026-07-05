import client from './client'

export interface Job {
  id: number
  connection_id: number
  trigger: string
  status: string
  error: string | null
  db_name: string | null
  started_at: string
  finished_at: string | null
}

export interface JobRecordRef {
  record_id: number
  db_name: string | null
  status: string
}

export interface JobRunResponse {
  connection_id: number
  record_ids: number[]
  records: JobRecordRef[]
  status: string
}

export const runBackup = (connection_id: number) =>
  client.post<JobRunResponse>('/backups/run', { connection_id })
export const listJobs = () => client.get<Job[]>('/jobs')
export const cancelJob = (id: number) => client.post(`/jobs/${id}/cancel`)
