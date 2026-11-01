import client from './client'

export interface NotificationGlobal {
  notify_on_success: boolean
  notify_on_failure: boolean
  notify_watchdog: boolean
}

export const getGlobalNotifications = () => client.get<NotificationGlobal>('/settings/notifications')
export const putGlobalNotifications = (data: NotificationGlobal) =>
  client.put<NotificationGlobal>('/settings/notifications', data)

export type ChannelType = 'email' | 'wechat' | 'feishu' | 'serverchan'

export interface Channel {
  id: number
  type: ChannelType
  name: string
  enabled: boolean
  config: Record<string, unknown>
  created_at: string
}

/** 创建/编辑请求体;secret 仅写入(编辑留空传 null 表示保留已存密文) */
export interface ChannelInput {
  type: ChannelType
  name: string
  enabled: boolean
  config: Record<string, unknown>
  secret?: Record<string, string> | null
}

export const listChannels = () => client.get<Channel[]>('/settings/notification-channels')
export const createChannel = (data: ChannelInput) =>
  client.post<Channel>('/settings/notification-channels', data)
export const updateChannel = (id: number, data: ChannelInput) =>
  client.put<Channel>(`/settings/notification-channels/${id}`, data)
export const deleteChannel = (id: number) =>
  client.delete<{ deleted: number }>(`/settings/notification-channels/${id}`)
export const testChannel = (id: number) =>
  client.post<{ id: number; name: string; type: string; ok: boolean; error: string | null }>(
    `/settings/notification-channels/${id}/test`)
export const testAllChannels = () =>
  client.post<Array<{ id: number; name: string; type: string; ok: boolean; error: string | null }>>(
    '/settings/notifications/test')

export interface VerifySettings {
  auto_enabled: boolean
}

export const getVerifySettings = () => client.get<VerifySettings>('/settings/verify')
export const putVerifySettings = (data: VerifySettings) => client.put<VerifySettings>('/settings/verify', data)
