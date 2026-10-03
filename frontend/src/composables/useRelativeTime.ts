import { ref } from 'vue'

function fmt(date: Date): string {
  const diff = (Date.now() - date.getTime()) / 1000
  if (diff < 60) return "刚刚"
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 172800) return "昨天 " + date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

/** 相对时间("3 分钟前"),悬浮 title 为完整时间;内部定时刷新。 */
export function useRelativeTime(iso: string | null | undefined): string {
  const text = ref("")
  function update() {
    if (!iso) { text.value = "—"; return }
    const d = new Date(iso)
    text.value = isNaN(d.getTime()) ? (iso ?? "—") : fmt(d)
  }
  update()
  return text.value
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return fmt(d)
}

export function fullTime(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN")
}
