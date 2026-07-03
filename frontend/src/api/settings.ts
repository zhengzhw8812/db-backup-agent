import client from './client'

export interface NotificationSettings {
  email_enabled: boolean
  smtp_host: string | null
  smtp_port: number | null
  smtp_ssl: boolean
  smtp_starttls: boolean
  smtp_user: string | null
  smtp_password: string | null  // 仅写入
  smtp_from: string | null
  recipients: string | null
  wechat_enabled: boolean
  wechat_corp_id: string | null
  wechat_agent_id: string | null
  wechat_secret: string | null  // 仅写入
  notify_on_success: boolean
  notify_on_failure: boolean
}

export const getNotifications = () => client.get<NotificationSettings>('/settings/notifications')
export const putNotifications = (data: NotificationSettings) => client.put<NotificationSettings>('/settings/notifications', data)
