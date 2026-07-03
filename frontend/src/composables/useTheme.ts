import { computed } from 'vue'
import { darkTheme } from 'naive-ui'
import { useThemeStore } from '../stores/theme'
import { lightOverrides, darkOverrides } from '../themes/tokens'

export function useTheme() {
  const store = useThemeStore()
  const theme = computed(() => (store.dark ? darkTheme : null))
  const overrides = computed(() => (store.dark ? darkOverrides : lightOverrides))
  return { theme, overrides, dark: computed(() => store.dark), toggle: store.toggle }
}
