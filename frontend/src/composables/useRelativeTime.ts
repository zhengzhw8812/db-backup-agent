import { ref } from 'vue'

/** 后端时间为 naive UTC ISO(无时区标记):补 Z 后解析,显示为浏览器本地时区。
 * 已带 offset/Z 的串(历史数据可能存在)原样解析,不做双补。 */
export function parseTs(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?(\d\d)?$/.test(iso) ? iso : iso + "Z")
}

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
    const d = parseTs(iso)
    text.value = isNaN(d.getTime()) ? (iso ?? "—") : fmt(d)
  }
  update()
  return text.value
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = parseTs(iso)
  if (isNaN(d.getTime())) return iso
  return fmt(d)
}

export function fullTime(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = parseTs(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN")
}
