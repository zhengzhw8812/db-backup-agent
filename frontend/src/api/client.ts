import axios from 'axios'
import router from '../router'

const client = axios.create({ baseURL: '/api/v1', withCredentials: true })

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) router.push('/login')
    return Promise.reject(err)
  },
)

export default client
