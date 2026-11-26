import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('clm_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const detail = error.response?.data?.detail
    if (Array.isArray(detail)) {
      error.message = detail.map((d) => d.msg).join('；')
    } else if (detail && typeof detail === 'object') {
      error.message = detail.message || '请求失败'
      error.conflicts = detail.conflicts
    } else if (typeof detail === 'string') {
      error.message = detail
    } else {
      error.message = error.message || '网络错误'
    }
    return Promise.reject(error)
  },
)

export default api
