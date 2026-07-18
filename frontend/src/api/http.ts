import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  timeout: 60000,
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err?.response?.data?.detail
    const message = typeof detail === 'string' ? detail : err.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export default http
