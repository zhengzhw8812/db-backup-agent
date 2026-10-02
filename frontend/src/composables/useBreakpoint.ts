import { computed, onMounted, onUnmounted, ref } from 'vue'

// 单例:全应用共享一个 matchMedia 监听(1024px 与 SoybeanAdmin 平板断点对齐)
const isMobileRef = ref(false)
let bound = false
let mql: MediaQueryList | null = null

function bind() {
  if (bound || typeof window === 'undefined') return
  bound = true
  mql = window.matchMedia('(max-width: 1023px)')
  isMobileRef.value = mql.matches
  mql.addEventListener('change', (e) => { isMobileRef.value = e.matches })
}

export function useBreakpoint() {
  bind()
  return {
    isMobile: computed(() => isMobileRef.value),
    isDesktop: computed(() => !isMobileRef.value),
  }
}
