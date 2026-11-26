<template>
  <div class="container" v-if="claim">
    <router-link to="/" class="back-link">← 返回报案列表</router-link>

    <div class="panel">
      <h2>
        {{ claim.claim_no }}
        <span class="tag tag-gray">{{ claim.policy.policy_no }}</span>
      </h2>
      <p class="muted" style="margin:4px 0">{{ claim.event_desc }}｜事故时间：{{ formatTime(claim.event_time) }}</p>
      <table>
        <tr>
          <th style="width:120px">保险标的</th><td>{{ claim.policy.subject }}</td>
          <th style="width:120px">保障期间</th>
          <td>{{ claim.policy.coverage_start }} 至 {{ claim.policy.coverage_end }}</td>
        </tr>
        <tr>
          <th>事故免赔额</th><td class="num">¥{{ claim.policy.deductible }}（一次事故共享，不逐项重复扣）</td>
          <th>事故赔偿上限</th><td class="num">¥{{ claim.policy.limit_amount }}</td>
        </tr>
        <tr>
          <th>收款人</th><td>{{ claim.policy.payee_name }}</td>
          <th>收款账号</th><td class="num">{{ claim.policy.payee_account }}</td>
        </tr>
      </table>
    </div>

    <div class="panel">
      <h2>合同核算（事件级）</h2>
      <div class="grid-3">
        <div class="money-card sub-card"><div class="v">¥{{ claim.money.approved_total }}</div><div class="k">认可损失总额</div></div>
        <div class="money-card sub-card"><div class="v">¥{{ claim.money.cumulative_indemnity }}</div><div class="k">累计应赔额（扣一次免赔、受上限约束）</div></div>
        <div class="money-card sub-card"><div class="v" style="color:var(--ok)">¥{{ claim.money.succeeded_total }}</div><div class="k">已成功支付</div></div>
        <div class="money-card sub-card"><div class="v" style="color:var(--warn)">¥{{ claim.money.reserved_total }}</div><div class="k">在途/锁定占用（结果未知不释放）</div></div>
        <div class="money-card sub-card"><div class="v" style="color:var(--primary)">¥{{ claim.money.remaining_liability }}</div><div class="k">剩余合同责任</div></div>
        <div class="money-card sub-card"><div class="v">¥{{ claim.money.deductible }} / ¥{{ claim.money.limit_amount }}</div><div class="k">免赔额 / 上限</div></div>
      </div>
    </div>

    <div class="panel stage-banner" :class="claim.progress.stage">
      <h2>
        当前办理状态：
        <span class="tag" :class="stageCls">{{ stageText }}</span>
      </h2>
      <div v-if="claim.progress.blockers.length">
        <strong>阻塞原因：</strong>
        <ul class="tight">
          <li v-for="(b, i) in claim.progress.blockers" :key="i">{{ b }}</li>
        </ul>
      </div>
      <div>
        <strong>可继续动作：</strong>
        <ul class="tight">
          <li v-for="(a, i) in claim.progress.actions" :key="i">{{ a }}</li>
        </ul>
      </div>
    </div>

    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="notice" class="alert alert-ok">{{ notice }}</div>

    <ItemsPanel :claim="claim" @changed="reload" @error="showError" />
    <OffersPanel :claim="claim" @changed="reload" @error="showError" />
    <BatchesPanel :claim="claim" @changed="reload" @error="showError" />
    <PaymentsPanel :claim="claim" @changed="reload" @error="showError" />
    <CorrectionsPanel :claim="claim" @changed="reload" @error="showError" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../api'
import { STAGE } from '../labels'
import ItemsPanel from '../components/ItemsPanel.vue'
import OffersPanel from '../components/OffersPanel.vue'
import BatchesPanel from '../components/BatchesPanel.vue'
import PaymentsPanel from '../components/PaymentsPanel.vue'
import CorrectionsPanel from '../components/CorrectionsPanel.vue'

const props = defineProps({ id: [String, Number] })
const claim = ref(null)
const error = ref('')
const notice = ref('')

const stageText = computed(() => STAGE[claim.value.progress.stage] || claim.value.progress.stage)
const stageClsMap = {
  survey_pending: 'tag-gray',
  awaiting_evidence: 'tag-blue',
  awaiting_acceptance: 'tag-purple',
  awaiting_payment: 'tag-blue',
  payment_unknown: 'tag-amber',
  in_progress: 'tag-amber',
  completed: 'tag-green',
}
const stageCls = computed(() => stageClsMap[claim.value.progress.stage] || 'tag-gray')

async function load() {
  const { data } = await api.get(`/claims/${props.id}`)
  claim.value = data
}
function reload() {
  notice.value = '操作成功，页面已刷新'
  load()
  setTimeout(() => (notice.value = ''), 2500)
}
function showError(msg) {
  error.value = msg
  setTimeout(() => (error.value = ''), 6000)
}
function formatTime(s) {
  return s ? s.replace('T', ' ').slice(0, 16) : ''
}
onMounted(load)
</script>
