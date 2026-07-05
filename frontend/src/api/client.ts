import axios from 'axios'
import router from '../router'

const client = axios.create({ baseURL: '/api/v1', withCredentials: true })

client.interceptors.response.use(
  (r) => r,
  async (err) => {
    if (err.response?.status === 401) {
      // 清空本地登录态(动态导入避免与 auth store 的循环依赖),
      // 否则 router 守卫仍认为已登录 → /login 被 bounce 回 / → 再次 401 → 死循环
      try {
        const { useAuthStore } = await import('../stores/auth')
        useAuthStore().clear()
      } catch { /* pinia 未就绪时忽略 */ }
      if (router.currentRoute.value.path !== '/login') router.push('/login')
    }
    return Promise.reject(err)
  },
)

export default client
