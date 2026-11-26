"""模型 → 可 JSON 序列化 dict。金额统一为字符串（Decimal 避免前端浮点误差）。"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from .enums import (
    BatchStatus,
    ItemStatus,
    MaterialStatus,
    OfferStatus,
    PaymentStatus,
)
from .models import (
    Claim,
    CorrectionCase,
    LossItem,
    Material,
    Offer,
    Payment,
    Policy,
    SettlementBatch,
    User,
)
from .services.calc import money_snapshot, recognized_items, unresolved_items


def money(v: Decimal | None) -> str | None:
    return None if v is None else str(v.quantize(Decimal("0.01")))


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role.value}


def policy_out(p: Policy) -> dict:
    return {
        "id": p.id,
        "policy_no": p.policy_no,
        "subject": p.subject,
        "coverage_start": p.coverage_start.isoformat(),
        "coverage_end": p.coverage_end.isoformat(),
        "deductible": money(p.deductible),
        "limit_amount": money(p.limit_amount),
        "payee_name": p.payee_name,
        "payee_account": p.payee_account,
    }


def material_out(m: Material) -> dict:
    return {
        "id": m.id,
        "status": m.status.value,
        "request_note": m.request_note,
        "file_name": m.file_name,
        "file_note": m.file_note,
        "review_note": m.review_note,
        "submitted_at": m.submitted_at.isoformat() if m.submitted_at else None,
        "created_at": m.created_at.isoformat(),
    }


def _item_batches(db: Session, item_id: int) -> list[dict]:
    from .models import BatchItem

    rows = db.query(BatchItem).filter(BatchItem.item_id == item_id).all()
    out = []
    for bi in rows:
        b = db.get(SettlementBatch, bi.batch_id)
        out.append(
            {
                "batch_id": b.id,
                "kind": b.kind,
                "status": b.status.value,
                "snapshot_amount": money(bi.snapshot_amount),
            }
        )
    return out


def item_out(db: Session, it: LossItem) -> dict:
    return {
        "id": it.id,
        "seq": it.seq,
        "title": it.title,
        "category": it.category,
        "claimed_amount": money(it.claimed_amount),
        "approved_amount": money(it.approved_amount),
        "status": it.status.value,
        "revision": it.revision,
        "dispute_reason": it.dispute_reason,
        "materials": [material_out(m) for m in it.materials],
        "batches": _item_batches(db, it.id),
    }


def offer_out(db: Session, o: Offer) -> dict:
    return {
        "id": o.id,
        "status": o.status.value,
        "note": o.note,
        "conflict_note": o.conflict_note,
        "created_at": o.created_at.isoformat(),
        "decided_at": o.decided_at.isoformat() if o.decided_at else None,
        "items": [
            {
                "item_id": oi.item_id,
                "quoted_amount": money(oi.quoted_amount),
                "snapshot_amount": money(oi.snapshot_amount),
                "snapshot_revision": oi.snapshot_revision,
                "current_revision": db.get(LossItem, oi.item_id).revision,
                "current_approved": money(db.get(LossItem, oi.item_id).approved_amount),
            }
            for oi in o.offer_items
        ],
    }


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id,
        "batch_id": p.batch_id,
        "amount": money(p.amount),
        "status": p.status.value,
        "gateway_outcome": p.gateway_outcome,
        "gateway_ref": p.gateway_ref,
        "poll_count": p.poll_count,
        "last_note": p.last_note,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
        "events": [
            {"event_type": e.event_type, "detail": e.detail, "created_at": e.created_at.isoformat()}
            for e in p.events
        ],
    }


def batch_out(db: Session, b: SettlementBatch) -> dict:
    return {
        "id": b.id,
        "kind": b.kind,
        "status": b.status.value,
        "expected_amount": money(b.expected_amount),
        "cancel_reason": b.cancel_reason,
        "accepted_at": b.accepted_at.isoformat() if b.accepted_at else None,
        "created_at": b.created_at.isoformat(),
        "items": [
            {
                "item_id": bi.item_id,
                "title": db.get(LossItem, bi.item_id).title,
                "snapshot_amount": money(bi.snapshot_amount),
                "snapshot_revision": bi.snapshot_revision,
            }
            for bi in b.batch_items
        ],
        "payments": [payment_out(p) for p in b.payments],
    }


def correction_out(db: Session, c: CorrectionCase) -> dict:
    it = db.get(LossItem, c.item_id)
    p = db.get(Payment, c.payment_id)
    return {
        "id": c.id,
        "item_id": c.item_id,
        "item_title": it.title if it else "",
        "payment_id": c.payment_id,
        "payment_amount": money(p.amount) if p else None,
        "status": c.status.value,
        "reason": c.reason,
        "process_note": c.process_note,
        "created_at": c.created_at.isoformat(),
        "processed_at": c.processed_at.isoformat() if c.processed_at else None,
    }


# ---------------------------------------------------------------------------
# 报案详情聚合：五类状态（待补证 / 待接受 / 待付款 / 支付结果未知 / 已完成）
# 每项均给出阻塞原因与可继续动作。
# ---------------------------------------------------------------------------

def _stage_and_blockers(db: Session, claim: Claim) -> dict:
    blockers: list[str] = []
    actions: list[str] = []
    stage: str

    unresolved = unresolved_items(db, claim.id)
    open_offers = [
        o for o in db.query(Offer).filter(Offer.claim_id == claim.id).all()
        if o.status == OfferStatus.OPEN
    ]
    pending_materials = [
        m
        for it in claim.items
        for m in it.materials
        if m.status in (MaterialStatus.PENDING, MaterialStatus.SUBMITTED)
    ]
    accepted_batches = [b for b in claim.batches if b.status == BatchStatus.ACCEPTED]
    pending_batches = [b for b in claim.batches if b.status == BatchStatus.PENDING_ACCEPTANCE]
    unknown_payments = [
        p
        for p in claim.payments
        if p.status in (PaymentStatus.SUBMITTED_UNKNOWN, PaymentStatus.TIMED_OUT)
    ]
    succeeded = [p for p in claim.payments if p.status == PaymentStatus.SUCCEEDED]
    declined = [p for p in claim.payments if p.status == PaymentStatus.DECLINED]
    locked = [p for p in claim.payments if p.status == PaymentStatus.LOCKED]

    if unknown_payments:
        stage = "payment_unknown"
        blockers.append("存在支付结果未知的在途付款，须凭网关交易号查询回执，禁止重复发起付款")
        actions.append("付款复核员：查询回执（/payments/{id}/query）")
    elif pending_materials:
        stage = "awaiting_evidence"
        pending_req = [m for m in pending_materials if m.status == MaterialStatus.PENDING]
        submitted_wait = [m for m in pending_materials if m.status == MaterialStatus.SUBMITTED]
        if pending_req:
            blockers.append(f"{len(pending_req)} 项补证请求待报案人上传材料")
            actions.append("报案人：在损失项目上补交材料")
        if submitted_wait:
            blockers.append(f"{len(submitted_wait)} 份补交材料待理算员审核")
            actions.append("理算员：审核补交材料，认可金额或继续争议")
    elif open_offers:
        stage = "awaiting_acceptance"
        blockers.append(f"{len(open_offers)} 份报价待报案人接受/拒绝；接受期间认可金额变化将产生可见冲突")
        actions.append("报案人：逐批接受或拒绝报价；理算员：可修订后重新报价")
    elif pending_batches:
        stage = "awaiting_acceptance"
        blockers.append(f"{len(pending_batches)} 个和解批次待报案人接受")
        actions.append("报案人：接受和解批次")
    elif accepted_batches or locked:
        stage = "awaiting_payment"
        if declined:
            blockers.append(f"{len(declined)} 笔付款被网关明确拒绝，可由复核员重新发起（原付款不占额度）")
        blockers.append(f"{len(accepted_batches)} 个已接受批次待付款复核员发起支付")
        actions.append("付款复核员：选择支付模拟模式发起支付")
    elif succeeded and not unresolved:
        stage = "completed"
        actions.append("案件全部责任履行完毕；若已付款项目再发现错误，只能建立人工更正案件")
    elif succeeded:
        stage = "in_progress"
        blockers.append(f"尚有 {len(unresolved)} 个争议/未认可项目未了结，后续按补差批次处理")
        actions.append("查勘员/理算员：继续处理争议项目；报案人可查看办理进度")
    else:
        stage = "survey_pending"
        blockers.append("损失项目尚在查勘/理算环节")
        actions.append("查勘员：确认事故损坏与认可金额；理算员：对争议项补证或报价")

    return {"stage": stage, "blockers": blockers, "actions": actions}


def claim_detail(db: Session, claim: Claim) -> dict:
    snap = money_snapshot(db, claim)
    return {
        "id": claim.id,
        "claim_no": claim.claim_no,
        "event_time": claim.event_time.isoformat(),
        "event_desc": claim.event_desc,
        "policy": policy_out(claim.policy),
        "money": {
            "approved_total": money(snap.approved_total),
            "deductible": money(snap.deductible),
            "limit_amount": money(snap.limit_amount),
            "cumulative_indemnity": money(snap.cumulative_indemnity),
            "succeeded_total": money(snap.succeeded_total),
            "reserved_total": money(snap.reserved_total),
            "remaining_liability": money(snap.remaining_liability),
        },
        "items": [item_out(db, it) for it in claim.items],
        "offers": [offer_out(db, o) for o in db.query(Offer).filter(Offer.claim_id == claim.id).all()],
        "batches": [batch_out(db, b) for b in claim.batches],
        "payments": [payment_out(p) for p in claim.payments],
        "corrections": [
            correction_out(db, c)
            for c in db.query(CorrectionCase).filter(CorrectionCase.claim_id == claim.id).all()
        ],
        "progress": _stage_and_blockers(db, claim),
        "recognized_item_ids": [it.id for it in recognized_items(db, claim.id)],
        "unresolved_item_ids": [it.id for it in unresolved_items(db, claim.id)],
    }
