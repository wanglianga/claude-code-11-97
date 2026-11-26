export const ITEM_STATUS = {
  submitted: ['待查勘', 'tag-gray'],
  recognized: ['已认可', 'tag-green'],
  disputed: ['争议中', 'tag-red'],
  recognized_after_dispute: ['争议后认可', 'tag-green'],
}

export const MATERIAL_STATUS = {
  pending: ['待补证', 'tag-red'],
  submitted: ['已提交待审核', 'tag-amber'],
  accepted: ['审核通过', 'tag-green'],
  rejected: ['审核不通过', 'tag-red'],
}

export const OFFER_STATUS = {
  open: ['待接受', 'tag-amber'],
  accepted: ['已接受', 'tag-green'],
  rejected: ['已拒绝', 'tag-gray'],
  conflicted: ['冲突失效', 'tag-red'],
}

export const BATCH_STATUS = {
  pending_acceptance: ['待接受', 'tag-amber'],
  accepted: ['待付款', 'tag-blue'],
  paid: ['已付清', 'tag-green'],
  cancelled: ['已作废', 'tag-gray'],
}

export const PAYMENT_STATUS = {
  locked: ['已锁定', 'tag-amber'],
  submitted_unknown: ['支付结果未知', 'tag-amber'],
  timed_out: ['提交超时·结果未知', 'tag-amber'],
  succeeded: ['支付成功', 'tag-green'],
  declined: ['网关拒绝', 'tag-red'],
}

export const STAGE = {
  survey_pending: '查勘理算中',
  awaiting_evidence: '待补证',
  awaiting_acceptance: '待接受',
  awaiting_payment: '待付款',
  payment_unknown: '支付结果未知',
  in_progress: '部分履行中',
  completed: '已完成',
}

export const GATEWAY_OPTIONS = [
  { value: 'success', label: '即时成功并返回回执' },
  { value: 'success_receipt_lost', label: '成功但响应丢失（稍后查询成功）' },
  { value: 'late_success', label: '提交超时，第二次查询才成功' },
  { value: 'decline', label: '网关明确拒绝' },
]

export function tag(map, key) {
  const entry = map[key] || [key, 'tag-gray']
  return { text: entry[0], cls: entry[1] }
}
