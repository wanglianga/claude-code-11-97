<template>
  <div class="container">
    <div class="panel login-card">
      <h2>登录理赔平台</h2>
      <div v-if="error" class="alert alert-error">{{ error }}</div>
      <label class="field">用户名</label>
      <input v-model="username" placeholder="reporter / surveyor / adjuster / officer_zhao" />
      <label class="field">密码</label>
      <input v-model="password" type="password" placeholder="test1234" @keyup.enter="submit" />
      <button style="width: 100%; margin-top: 6px" @click="submit">登录</button>
      <div class="role-hint" style="margin-top: 14px">
        测试账号（密码均为 test1234）：<br />
        reporter 张报案（报案人） · surveyor 李查勘（查勘员）<br />
        adjuster 王理算（理算员） · officer_zhao 赵复核 / officer_qian 钱复核（付款复核员）
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { useAuthStore } from '../store'

const username = ref('reporter')
const password = ref('test1234')
const error = ref('')
const router = useRouter()
const auth = useAuthStore()

async function submit() {
  error.value = ''
  try {
    const { data } = await api.post('/auth/login', {
      username: username.value,
      password: password.value,
    })
    auth.setSession(data.token, data.user)
    router.push('/')
  } catch (e) {
    error.value = e.message
  }
}
</script>
