import { ref, onUnmounted } from 'vue'

export interface JobEvent {
  id: number
  stage: string
  detail: string
}

const TERMINAL = ['success', 'failed', 'cancelled']
// EventSource 断线会无限自动重连;连续失败超过阈值则判定任务失联,停止重连
const MAX_FAILURES = 5

export function useJobStream() {
  const events = ref<JobEvent[]>([])
  const status = ref<string>('idle')
  let es: EventSource | null = null
  let failCount = 0
  let seq = 0  // 事件单调递增 id,用作 v-for key(避免用数组索引在重订阅时复用 DOM)

  function subscribe(recordId: number, urlFor: (id: number) => string = (id) => `/api/v1/jobs/${id}/events`) {
    close()
    events.value = []
    status.value = 'running'
    failCount = 0
    es = new EventSource(urlFor(recordId), { withCredentials: true })
    es.onmessage = (e) => {
      failCount = 0 // 收到任一消息即视为连接健康
      try {
        const data = JSON.parse(e.data) as Omit<JobEvent, 'id'>
        events.value.push({ id: ++seq, ...data })
        if (TERMINAL.includes(data.stage)) {
          status.value = data.stage
          es?.close()
        }
      } catch {
        /* ignore malformed */
      }
    }
    es.onerror = () => {
      // 连续断线超过阈值:放弃重连,置为 failed(避免无限重连风暴 + UI 永久 running)
      if (++failCount >= MAX_FAILURES) {
        status.value = 'failed'
        es?.close()
      }
    }
  }

  function close() {
    es?.close()
    es = null
  }

  onUnmounted(close)
  return { events, status, subscribe, close }
}
