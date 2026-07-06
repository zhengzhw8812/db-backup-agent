import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useMessage } from 'naive-ui'

/** 登录表单的共用状态 + 提交逻辑(两个登录变体共用,避免重复)。 */
export function useLogin() {
  const username = ref('')
  const password = ref('')
  const loading = ref(false)
  const auth = useAuthStore()
  const router = useRouter()
  const msg = useMessage()

  async function submit() {
    if (!username.value.trim() || !password.value) {
      msg.warning('请输入用户名和密码')
      return
    }
    loading.value = true
    try {
      await auth.doLogin(username.value, password.value)
      router.push('/')
    } catch {
      msg.error('用户名或密码错误')
    } finally {
      loading.value = false
    }
  }

  return { username, password, loading, submit }
}
