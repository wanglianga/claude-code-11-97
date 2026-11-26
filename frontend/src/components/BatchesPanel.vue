<template>
  <div class="panel">
    <h2>和解批次与接受 <span class="muted" style="font-weight:400">（部分和解可早拿首款；整案和解减少轮次。免赔仅事故层核算一次）</span></h2>

    <div v-if="auth.isAdjuster" class="sub-card">
      <h3 style="margin-top:0">理算员组建批次</h3>
      <div class="inline-form">
        <label class="field">办理方式
          <select v-model="kind">
            <option value="partial">部分和解（仅纳入所选已认可项目）</option>
            <option value="whole_case">整案和解（须全部项目了结）</option>
          </select>
        </label>
        <label class="field" v-if="kind === 'partial'">纳入项目
          <select multiple v-model="itemIds" style="height:84px">
            <option v-for="i in recognizedItems" :key="i.id" :value="i.id">
              #{{ i.seq }} {{ i.title }}（认可 ¥{{ i.approved_amount }}）
            </option>
          </select>
        </label>
        <button @click="createBatch">组建和解批次</button>
      </div>
      <p class="muted" style="margin:6px 0 0">
        部分和解后，争议项目后续认可时可再建补差批次；两条路径最终履行同一份合同责任。
      </p>
    </div>

    <div v-if="!claim.batches.length" class="muted">暂无和解批次。</div>
    <div v-for="b in claim.batches" :key="b.id" class="sub-card">
      <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
        <strong>批次 #{{ b.id }}</strong>
        <span class="tag tag-purple">{{ b.kind === 'partial' ? '部分和解' : '整案和解' }}</span>
        <span class="tag" :class="batchTag(b.status).cls">{{ batchTag(b.status).text }}</span>
        <span class="muted">预期可付 ¥{{ b.expected_amount }}</span>
      </div>
      <table style="margin-top:8px">
        <thead><tr><th>项目</th><th>接受时金额快照</th><th>修订快照</th></tr></thead>
        <tbody>
          <tr v-for="bi in b.items" :key="bi.item_id">
            <td>#{{ bi.item_id }} {{ bi.title }}</td>
            <td class="num">¥{{ bi.snapshot_amount }}</td>
            <td>r{{ bi.snapshot_revision }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="b.cancel_reason" class="alert alert-warn" style="margin-top:8px">作废原因：{{ b.cancel_reason }}</div>
      <div v-if="auth.isReporter && b.status === 'pending_acceptance'" style="margin-top:8px">
        <button @click="accept(b.id, true)">接受批次</button>
        <button class="danger" @click="accept(b.id, false)">拒绝（作废）</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import api from '../api'
import { useAuthStore } from '../store'
import { BATCH_STATUS, tag } from '../labels'

const props = defineProps({ claim: Object })
const emit = defineEmits(['changed', 'error'])
const auth = useAuthStore()
const batchTag = (k) => tag(BATCH_STATUS, k)

const recognizedItems = computed(() =>
  props.claim.items.filter((i) => claimRecognized(i.status)),
)
function claimRecognized(s) {
  return s === 'recognized' || s === 'recognized_after_dispute'
}

const kind = ref('partial')
const itemIds = ref([])

async function call(fn) {
  try { await fn(); emit('changed') } catch (e) { emit('error', e.message) }
}
function createBatch() {
  const body = kind.value === 'whole_case'
    ? { kind: 'whole_case' }
    : { kind: 'partial', item_ids: itemIds.value.map(Number) }
  call(() => api.post(`/claims/${props.claim.id}/batches`, body))
}
function accept(batchId, accepted) {
  call(() => api.post(`/batches/${batchId}/accept`, { accepted }))
}
</script>
