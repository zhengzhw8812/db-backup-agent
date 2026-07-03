import client from './client'

export interface Schedule {
  id: number
  connection_id: number
  cron_expr: string
  enabled: boolean
  retention_days: number
  next_run_at: string | null
}
export type SchedulePayload = Partial<Omit<Schedule, 'id' | 'next_run_at'>>

export const listSchedules = () => client.get<Schedule[]>('/schedules')
export const createSchedule = (data: SchedulePayload) => client.post<Schedule>('/schedules', data)
export const updateSchedule = (id: number, data: SchedulePayload) => client.put<Schedule>(`/schedules/${id}`, data)
export const deleteSchedule = (id: number) => client.delete(`/schedules/${id}`)
