<template>
  <div class="app-header">
    <h1>🏚️ 地震理赔办理平台</h1>
    <span class="role-badge" v-if="auth.user">{{ auth.user.display_name }} · {{ roleText }}</span>
    <div class="spacer"></div>
    <router-link to="/" v-if="auth.token" style="margin-right: 12px">报案列表</router-link>
    <button class="secondary" v-if="auth.token" @click="logout">退出登录</button>
  </div>
  <router-view />
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from './store'

const auth = useAuthStore()
const router = useRouter()
const roleNames = {
  reporter: '报案人',
  surveyor: '查勘员',
  adjuster: '理算员',
  pay_officer: '付款复核员',
}
const roleText = computed(() => roleNames[auth.role] || auth.role)

function logout() {
  auth.logout()
  router.push('/login')
}
</script>
