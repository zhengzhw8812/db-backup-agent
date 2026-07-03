import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '../api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<{ id: number; username: string; totp_enabled: boolean } | null>(null)
  const ready = ref(false)

  async function fetchMe() {
    try { user.value = (await authApi.me()).data } catch { user.value = null }
    ready.value = true
  }
  async function doLogin(username: string, password: string) {
    user.value = (await authApi.login(username, password)).data
  }
  async function doLogout() { await authApi.logout(); user.value = null }

  return { user, ready, fetchMe, doLogin, doLogout }
})
