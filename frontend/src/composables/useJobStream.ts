import { ref, onUnmounted } from 'vue'

export interface JobEvent {
  stage: string
  detail: string
}

export function useJobStream() {
  const events = ref<JobEvent[]>([])
  const status = ref<string>('idle')
  let es: EventSource | null = null

  function subscribe(recordId: number, urlFor: (id: number) => string = (id) => `/api/v1/jobs/${id}/events`) {
    close()
    events.value = []
    status.value = 'running'
    es = new EventSource(urlFor(recordId), { withCredentials: true })
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as JobEvent
        events.value.push(data)
        if (['success', 'failed', 'cancelled'].includes(data.stage)) {
          status.value = data.stage
          es?.close()
        }
      } catch {
        /* ignore malformed */
      }
    }
    es.onerror = () => {
      /* transient reconnect or close; leave as-is */
    }
  }

  function close() {
    es?.close()
    es = null
  }

  onUnmounted(close)
  return { events, status, subscribe, close }
}
