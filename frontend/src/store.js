import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('clm_token') || '',
    user: JSON.parse(localStorage.getItem('clm_user') || 'null'),
  }),
  getters: {
    role: (s) => s.user?.role || '',
    isReporter: (s) => s.user?.role === 'reporter',
    isSurveyor: (s) => s.user?.role === 'surveyor',
    isAdjuster: (s) => s.user?.role === 'adjuster',
    isPayOfficer: (s) => s.user?.role === 'pay_officer',
  },
  actions: {
    setSession(token, user) {
      this.token = token
      this.user = user
      localStorage.setItem('clm_token', token)
      localStorage.setItem('clm_user', JSON.stringify(user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('clm_token')
      localStorage.removeItem('clm_user')
    },
  },
})
