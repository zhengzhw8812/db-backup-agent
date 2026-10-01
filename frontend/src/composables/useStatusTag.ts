import { h } from 'vue'
import { NTag } from 'naive-ui'

const MAP: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
  success: 'success', failed: 'error', running: 'info', cancelled: 'default',
}

/** 状态 → NTag 渲染函数(Backups/Restore/History 共用)。 */
export function useStatusTag() {
  return (s: string) =>
    h(NTag, { type: MAP[s] || 'default', size: 'small', bordered: false }, { default: () => s })
}
