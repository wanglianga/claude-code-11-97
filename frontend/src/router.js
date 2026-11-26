import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './store'
import LoginView from './views/LoginView.vue'
import ClaimsListView from './views/ClaimsListView.vue'
import ClaimDetailView from './views/ClaimDetailView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView },
    { path: '/', component: ClaimsListView },
    { path: '/claims/:id', component: ClaimDetailView, props: true },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.path !== '/login' && !auth.token) return '/login'
  if (to.path === '/login' && auth.token) return '/'
})

export default router
