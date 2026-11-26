<template>
  <div class="panel">
    <h2>人工更正案件 <span class="muted" style="font-weight:400">（已付款项目发现错误，不静默修改历史付款）</span></h2>

    <details v-if="canOpen" style="margin-bottom:10px">
      <summary style="cursor:pointer; font-weight:600">＋ 建立人工更正案件</summary>
      <div style="margin-top:10px">
        <label class="field">涉及损失项目
          <select v-model="form.item_id">
            <option v-for="i in claim.items" :key="i.id" :value="i.id">#{{ i.seq }} {{ i.title }}</option>
          </select>
        </label>
        <label class="field">涉及历史付款
          <select v-model="form.payment_id">
            <option v-for="p in succeededPayments" :key="p.id" :value="p.id">
              付款 #{{ p.id }} ¥{{ p.amount }}（批次 #{{ p.batch_id }}）
            </option>
          </select>
        </label>
        <label class="field">更正原因<input v-model="form.reason" placeholder="发现的错误与依据" /></label>
        <button @click="openCase">提交更正案件</button>
      </div>
    </details>

    <div v-if="!claim.corrections.length" class="muted">暂无更正案件。</div>
    <div v-for="c in claim.corrections" :key="c.id" class="sub-card">
      <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
        <strong>更正案件 #{{ c.id }}</strong>
        <span class="tag" :class="c.status === 'open' ? 'tag-amber' : 'tag-green'">
          {{ c.status === 'open' ? '待人工处理' : '已处理' }}
        </span>
        <span class="muted">项目 #{{ c.item_id }} {{ c.item_title }} / 历史付款 #{{ c.payment_id }} ¥{{ c.payment_amount }}</span>
      </div>
      <p style="margin:8px 0 4px">原因：{{ c.reason }}</p>
      <p v-if="c.process_note" class="muted">处理结论：{{ c.process_note }}（历史付款记录保持不变）</p>
      <div v-if="auth.isPayOfficer && c.status === 'open'" class="inline-form" style="margin-top:8px">
        <label class="field">处理说明<input v-model="processForm[c.id]" placeholder="人工核查与后续处置" /></label>
        <button @click="process(c.id)">登记处理结论</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import api from '../api'
import { useAuthStore } from '../store'

const props = defineProps({ claim: Object })
const emit = defineEmits(['changed', 'error'])
const auth = useAuthStore()

const succeededPayments = computed(() => props.claim.payments.filter((p) => p.status === 'succeeded'))
const canOpen = computed(() =>
  ['surveyor', 'adjuster', 'pay_officer'].includes(auth.role) && succeededPayments.value.length > 0,
)
const form = reactive({ item_id: '', payment_id: '', reason: '' })
const processForm = reactive({})

async function call(fn) {
  try { await fn(); emit('changed') } catch (e) { emit('error', e.message) }
}
function openCase() {
  call(() =>
    api.post(`/claims/${props.claim.id}/corrections`, {
      item_id: Number(form.item_id),
      payment_id: Number(form.payment_id),
      reason: form.reason,
    }),
  )
}
function process(caseId) {
  call(() => api.post(`/corrections/${caseId}/process`, { process_note: processForm[caseId] || '人工复核完成' }))
}
</script>
