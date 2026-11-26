<template>
  <div class="panel">
    <h2>分项损失与材料 <span class="muted" style="font-weight:400">（建筑 / 室内财产分项查勘，共享一次免赔与上限）</span></h2>
    <div v-for="item in claim.items" :key="item.id" class="sub-card">
      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap">
        <strong>#{{ item.seq }} {{ item.title }}</strong>
        <span class="tag" :class="itemTag(item.status).cls">{{ itemTag(item.status).text }}</span>
        <span class="tag tag-purple">修订号 r{{ item.revision }}</span>
        <span class="tag tag-gray">{{ item.category === 'building' ? '建筑' : '室内财产' }}</span>
        <span v-if="item.batches.length" class="tag tag-blue">
          已属批次：{{ item.batches.map((b) => '#' + b.batch_id + '(' + batchTag(b.status).text + ')').join('，') }}
        </span>
      </div>
      <table style="margin-top:8px">
        <tr><th style="width:130px">报案金额</th><td class="num">¥{{ item.claimed_amount }}</td>
            <th style="width:130px">认可金额</th><td class="num">{{ item.approved_amount ? '¥' + item.approved_amount : '—' }}</td></tr>
        <tr v-if="item.dispute_reason"><th>争议原因</th><td colspan="3" class="tag-red" style="color:var(--danger)">{{ item.dispute_reason }}</td></tr>
      </table>

      <h3>材料 / 补证记录</h3>
      <table>
        <thead><tr><th>状态</th><th>补证要求</th><th>已交材料</th><th>审核意见</th></tr></thead>
        <tbody>
          <tr v-for="m in item.materials" :key="m.id">
            <td><span class="tag" :class="matTag(m.status).cls">{{ matTag(m.status).text }}</span></td>
            <td>{{ m.request_note }}</td>
            <td>{{ m.file_name || '—' }} <span class="muted">{{ m.file_note }}</span></td>
            <td>{{ m.review_note || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <!-- 报案人：补交材料 -->
      <div v-for="m in item.materials.filter((x) => x.status === 'pending')" :key="'s' + m.id" class="inline-form" style="margin-top:8px">
        <label class="field">材料文件名<input v-model="subForm(m.id).name" placeholder="proof.pdf" /></label>
        <label class="field">材料说明<input v-model="subForm(m.id).note" placeholder="凭证说明" /></label>
        <button @click="submitMaterial(m.id)">补交材料</button>
      </div>

      <!-- 查勘员：查勘结论 -->
      <div v-if="auth.isSurveyor && !item.batches.some((b) => b.status !== 'cancelled')" class="inline-form" style="margin-top:8px">
        <label class="field">认可金额（留空=列争议）<input v-model="surForm(item.id).amount" type="number" placeholder="如 18000" /></label>
        <label class="field">争议原因（列争议时必填）<input v-model="surForm(item.id).reason" /></label>
        <button @click="survey(item.id)">提交查勘结论</button>
      </div>

      <!-- 理算员：发起补证 / 审核材料 / 争议后认可 -->
      <div v-if="auth.isAdjuster && item.status === 'disputed'" style="margin-top:8px">
        <div class="inline-form">
          <label class="field">补证要求<input v-model="requestForm[item.id]" placeholder="需要补充的凭证" /></label>
          <button class="secondary" @click="requestMaterial(item.id)">发起补证</button>
        </div>
        <div v-for="m in item.materials.filter((x) => x.status === 'submitted')" :key="'r' + m.id" class="inline-form">
          <label class="field">审核意见<input v-model="reviewForm[m.id]" placeholder="审核说明" /></label>
          <button @click="review(m.id, true)">审核通过</button>
          <button class="danger" @click="review(m.id, false)">驳回</button>
        </div>
      </div>
      <div v-if="(auth.isAdjuster || auth.isSurveyor) && item.status === 'disputed'" class="inline-form" style="margin-top:8px">
        <label class="field">争议后认可金额<input v-model="recognizeForm[item.id]" type="number" placeholder="如 8000" /></label>
        <button @click="recognize(item.id)">给予认可</button>
      </div>
    </div>

    <!-- 报案人新增损失项目 -->
    <details v-if="auth.isReporter" style="margin-top:10px">
      <summary style="cursor:pointer; font-weight:600">＋ 上传新的损失项目及材料</summary>
      <div class="grid-2" style="margin-top:10px">
        <label class="field">项目名称<input v-model="newItem.title" /></label>
        <label class="field">类别
          <select v-model="newItem.category"><option value="building">建筑</option><option value="indoor">室内财产</option></select>
        </label>
        <label class="field">报案金额<input v-model="newItem.claimed_amount" type="number" /></label>
        <label class="field">材料文件名<input v-model="newItem.file_name" /></label>
        <label class="field" style="grid-column:1/-1">材料说明<input v-model="newItem.file_note" /></label>
      </div>
      <button @click="addItem">上传损失项目</button>
    </details>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import api from '../api'
import { useAuthStore } from '../store'
import { ITEM_STATUS, MATERIAL_STATUS, BATCH_STATUS, tag } from '../labels'

const props = defineProps({ claim: Object })
const emit = defineEmits(['changed', 'error'])
const auth = useAuthStore()

const itemTag = (k) => tag(ITEM_STATUS, k)
const matTag = (k) => tag(MATERIAL_STATUS, k)
const batchTag = (k) => tag(BATCH_STATUS, k)

const surveyForm = reactive({})
const requestForm = reactive({})
const reviewForm = reactive({})
const recognizeForm = reactive({})
const submitForm = reactive({})
const newItem = reactive({ title: '', category: 'building', claimed_amount: '', file_name: '', file_note: '' })

// v-model 不能绑定可选链表达式，用辅助函数保证嵌套对象已初始化
function subForm(id) {
  if (!submitForm[id]) submitForm[id] = { name: '', note: '' }
  return submitForm[id]
}
function surForm(id) {
  if (!surveyForm[id]) surveyForm[id] = { amount: '', reason: '' }
  return surveyForm[id]
}

async function call(fn) {
  try { await fn(); emit('changed') } catch (e) { emit('error', e.message) }
}

function submitMaterial(materialId) {
  const f = submitForm[materialId] || {}
  call(() => api.post(`/materials/${materialId}/submit`, { file_name: f.name || '补交材料.pdf', file_note: f.note || '' }))
}
function survey(itemId) {
  const f = surveyForm[itemId] || {}
  const body = f.amount ? { approved_amount: String(f.amount) } : { dispute_reason: f.reason }
  call(() => api.post(`/items/${itemId}/survey`, body))
}
function requestMaterial(itemId) {
  call(() => api.post(`/items/${itemId}/material-request`, { request_note: requestForm[itemId] || '请补充相关凭证' }))
}
function review(materialId, accept) {
  call(() => api.post(`/materials/${materialId}/review`, { accept, review_note: reviewForm[materialId] || '' }))
}
function recognize(itemId) {
  call(() => api.post(`/items/${itemId}/recognize`, { approved_amount: String(recognizeForm[itemId]) }))
}
function addItem() {
  call(() => api.post(`/claims/${props.claim.id}/items`, { ...newItem, claimed_amount: String(newItem.claimed_amount) }))
}
</script>
