<template>
  <div class="panel">
    <h2>付款与支付模拟器 <span class="muted" style="font-weight:400">（虚构网关；超时/回执丢失不重新生成付款，只能查询）</span></h2>

    <div v-if="!claim.payments.length" class="muted">暂无付款记录。</div>

    <div v-for="p in claim.payments" :key="p.id" class="sub-card">
      <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
        <strong>付款 #{{ p.id }}</strong>
        <span class="tag" :class="payTag(p.status).cls">{{ payTag(p.status).text }}</span>
        <span class="num">¥{{ p.amount }}</span>
        <span class="tag tag-gray">批次 #{{ p.batch_id }}</span>
        <span class="tag tag-gray">网关交易号 {{ p.gateway_ref || '—' }}</span>
        <span class="muted">已查询 {{ p.poll_count }} 次</span>
      </div>
      <p style="margin:8px 0 4px">{{ p.last_note }}</p>
      <div class="event-log">
        <div v-for="(e, idx) in p.events" :key="idx">
          · {{ e.created_at.replace('T', ' ').slice(0, 19) }} 【{{ e.event_type }}】{{ e.detail }}
        </div>
      </div>

      <div v-if="auth.isPayOfficer && ['locked', 'submitted_unknown', 'timed_out'].includes(p.status)" style="margin-top:8px">
        <button @click="query(p.id)">查询网关回执</button>
        <span class="muted">结果未知期间该笔持续占用事故额度，禁止重复发起。</span>
      </div>
    </div>

    <div v-if="auth.isPayOfficer">
      <h3>对“待付款”批次发起支付（选择模拟结果模式）</h3>
      <div v-for="b in payableBatches" :key="b.id" class="inline-form">
        <label class="field" style="flex:0 0 260px">
          批次 #{{ b.id }}（{{ b.kind === 'partial' ? '部分和解' : '整案和解' }}，预期可付 ¥{{ b.expected_amount }}）
          <select v-model="outcomeForm[b.id]">
            <option v-for="o in gatewayOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </label>
        <button @click="pay(b.id)">发起支付</button>
      </div>
      <p v-if="!payableBatches.length" class="muted">没有待付款的已接受批次。</p>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import api from '../api'
import { useAuthStore } from '../store'
import { PAYMENT_STATUS, GATEWAY_OPTIONS, tag } from '../labels'

const props = defineProps({ claim: Object })
const emit = defineEmits(['changed', 'error'])
const auth = useAuthStore()
const payTag = (k) => tag(PAYMENT_STATUS, k)
const gatewayOptions = GATEWAY_OPTIONS

const payableBatches = computed(() => props.claim.batches.filter((b) => b.status === 'accepted'))
const outcomeForm = reactive({})

async function call(fn) {
  try { await fn(); emit('changed') } catch (e) { emit('error', e.message) }
}
function pay(batchId) {
  const outcome = outcomeForm[batchId] || 'success'
  call(() => api.post(`/batches/${batchId}/pay`, { gateway_outcome: outcome }))
}
function query(paymentId) {
  call(() => api.post(`/payments/${paymentId}/query`))
}
</script>
