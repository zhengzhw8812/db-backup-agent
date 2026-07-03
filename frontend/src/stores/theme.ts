import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const dark = ref(localStorage.getItem('theme') === 'dark')
  function toggle() { dark.value = !dark.value; localStorage.setItem('theme', dark.value ? 'dark' : 'light') }
  return { dark, toggle }
})
