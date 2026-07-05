import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '../api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<{ id: number; username: string } | null>(null)
  const ready = ref(false)

  async function fetchMe() {
    try {
      user.value = (await authApi.me()).data
    } catch (e: any) {
      // 仅 401/403 视为未登录;5xx/网络抖动不清空,避免后端瞬断把已登录用户踢到登录页
      if (e?.response?.status === 401 || e?.response?.status === 403) user.value = null
    }
    ready.value = true
  }
  async function doLogin(username: string, password: string) {
    user.value = (await authApi.login(username, password)).data
  }
  async function doLogout() {
    // 无论登出请求是否成功,客户端一律回到未登录态
    try { await authApi.logout() } finally { user.value = null }
  }
  function clear() {
    user.value = null
  }

  return { user, ready, fetchMe, doLogin, doLogout, clear }
})
