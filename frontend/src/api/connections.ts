import client from './client'

export type Connection = {
  id: number
  name: string
  type: 'pg' | 'mysql' | 'mongo' | 'redis' | 'sqlite'
  host?: string | null
  port?: number | null
  db_name?: string | null
  db_names?: string[] | null
  username?: string | null
  extra?: Record<string, unknown> | null
  created_at: string
}

export type ConnectionPayload = Partial<Omit<Connection, 'id' | 'created_at'>> & { password?: string }

export const listConnections = () => client.get<Connection[]>('/connections')
export const createConnection = (data: ConnectionPayload) => client.post<Connection>('/connections', data)
export const updateConnection = (id: number, data: ConnectionPayload) => client.put<Connection>(`/connections/${id}`, data)
export const deleteConnection = (id: number) => client.delete(`/connections/${id}`)

export type ListDatabasesPayload = {
  type: string
  host?: string | null
  port?: number | null
  username?: string | null
  password?: string
  db_name?: string | null
}

export const listDatabases = (payload: ListDatabasesPayload) =>
  client.post<{ databases: string[] }>('/connections/list-databases', payload)
export const listDatabasesForConnection = (id: number) =>
  client.post<{ databases: string[] }>(`/connections/${id}/databases`)
