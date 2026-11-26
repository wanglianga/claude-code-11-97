<template>
  <div class="panel">
    <h2>争议项目报价与接受 <span class="muted" style="font-weight:400">（报价绑定项目与材料修订快照，金额变化即冲突失效）</span></h2>

    <details v-if="auth.isAdjuster" style="margin-bottom:10px">
      <summary style="cursor:pointer; font-weight:600">＋ 理算员就争议项发起报价</summary>
      <div style="margin-top:10px">
        <label class="field" v-for="item in disputedItems" :key="item.id" style="display:inline-block; width:280px">
          <input type="checkbox" :value="item.id" v-model="selected" style="width:auto; margin-right:6px" />
          #{{ item.seq }} {{ item.title }}（报案 ¥{{ item.claimed_amount }}，r{{ item.revision }}）
        </label>
        <label class="field">报价说明<input v-model="note" /></label>
        <button @click="createOffer">发起报价</button>
      </div>
    </details>

    <div v-if="!claim.offers.length" class="muted">暂无报价。</div>
    <div v-for="offer in claim.offers" :key="offer.id" class="sub-card">
      <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap">
        <strong>报价 #{{ offer.id }}</strong>
        <span class="tag" :class="offerTag(offer.status).cls">{{ offerTag(offer.status).text }}</span>
        <span class="muted">{{ offer.note }}</span>
      </div>
      <table style="margin-top:8px">
        <thead><tr><th>项目</th><th>报价金额</th><th>报价时修订</th><th>当前修订</th><th>当前认可额</th></tr></thead>
        <tbody>
          <tr v-for="oi in offer.items" :key="oi.item_id">
            <td>#{{ oi.item_id }}</td>
            <td class="num">¥{{ oi.quoted_amount }}</td>
            <td>r{{ oi.snapshot_revision }}</td>
            <td :class="oi.current_revision !== oi.snapshot_revision ? 'tag-red' : ''" style="color: oi.current_revision !== oi.snapshot_revision ? 'var(--danger)' : ''">
              r{{ oi.current_revision }}
            </td>
            <td class="num">{{ oi.current_approved ? '¥' + oi.current_approved : '—' }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="offer.status === 'conflicted'" class="conflict-box">
        <strong>⚠ 可见冲突：</strong>{{ offer.conflict_note }}。旧报价不能按原金额成交，须由理算员基于最新结论重新报价。
      </div>

      <div v-if="auth.isAdjuster && offer.status === 'open'" style="margin-top:8px">
        <div v-for="oi in offer.items" :key="'q' + oi.item_id" class="inline-form">
          <label class="field">项目 #{{ oi.item_id }} 报价金额调整<input v-model="quoteForm[oi.item_id]" type="number" :placeholder="oi.quoted_amount" /></label>
          <button class="secondary" @click="adjustQuote(offer.id, oi.item_id)">调整报价</button>
        </div>
      </div>
      <div v-if="auth.isReporter && offer.status === 'open'" style="margin-top:8px">
        <button @click="decide(offer.id, true)">接受报价</button>
        <button class="danger" @click="decide(offer.id, false)">拒绝</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import api from '../api'
import { useAuthStore } from '../store'
import { OFFER_STATUS, tag } from '../labels'

const props = defineProps({ claim: Object })
const emit = defineEmits(['changed', 'error'])
const auth = useAuthStore()
const offerTag = (k) => tag(OFFER_STATUS, k)

const disputedItems = computed(() => props.claim.items.filter((i) => i.status === 'disputed'))
const selected = ref([])
const note = ref('')
const quoteForm = reactive({})

async function call(fn) {
  try { await fn(); emit('changed') } catch (e) {
    emit('error', e.conflicts ? `${e.message}：${e.conflicts.map((c) => '项目#' + c.item_id + ' r' + c.snapshot_revision + '→r' + c.current_revision).join('，')}` : e.message)
  }
}
function createOffer() {
  call(() => api.post('/offers', { item_ids: selected.value, note: note.value }))
}
function adjustQuote(offerId, itemId) {
  call(() => api.post(`/offers/${offerId}/quoted-amount`, { item_id: itemId, quoted_amount: String(quoteForm[itemId]) }))
}
function decide(offerId, accept) {
  call(() => api.post(`/offers/${offerId}/${accept ? 'accept' : 'reject'}`))
}
</script>
