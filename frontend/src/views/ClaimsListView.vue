<template>
  <div class="container">
    <div class="panel">
      <h2>地震报案列表</h2>
      <table>
        <thead>
          <tr><th>报案号</th><th>保单号</th><th>事故描述</th><th>事故时间</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="c in claims" :key="c.id">
            <td class="num">{{ c.claim_no }}</td>
            <td>{{ c.policy_no }}</td>
            <td>{{ c.event_desc }}</td>
            <td>{{ formatTime(c.event_time) }}</td>
            <td><router-link :to="`/claims/${c.id}`">进入办理 →</router-link></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../api'

const claims = ref([])
onMounted(async () => {
  const { data } = await api.get('/claims')
  claims.value = data
})

function formatTime(s) {
  return s ? s.replace('T', ' ').slice(0, 16) : ''
}
</script>
