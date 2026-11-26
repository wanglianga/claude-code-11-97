"""合同核算引擎。

规则（见题设示例合同）：
- 一次事故共享一次免赔额与一个赔偿上限，建筑与室内财产分项查勘但不逐项重复扣免赔；
- 累计应赔额 = max(0, 认可损失总额 - 事故免赔额)，再受事故上限约束；
- 某批可付额 = 累计应赔额 - 本事故已成功支付金额 - 已锁定/在途（结果未知）付款金额。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import ItemStatus, PaymentStatus
from ..models import Claim, LossItem, Payment

D = Decimal
RECOGNIZED_STATUSES = (ItemStatus.RECOGNIZED, ItemStatus.RECOGNIZED_AFTER_DISPUTE)
# 这些状态的付款仍占用事故额度：超时/回执丢失不等于失败，绝不重新生成另一笔付款
RESERVING_STATUSES = (
    PaymentStatus.LOCKED,
    PaymentStatus.SUBMITTED_UNKNOWN,
    PaymentStatus.TIMED_OUT,
)


def recognized_items(db: Session, claim_id: int) -> list[LossItem]:
    rows = db.scalars(
        select(LossItem)
        .where(LossItem.claim_id == claim_id)
        .where(LossItem.status.in_(RECOGNIZED_STATUSES))
        .order_by(LossItem.seq)
    ).all()
    return [it for it in rows if it.approved_amount is not None]


def unresolved_items(db: Session, claim_id: int) -> list[LossItem]:
    """尚未形成最终认可结论的分项（整案和解须等待这些项目了结）。"""
    rows = db.scalars(
        select(LossItem)
        .where(LossItem.claim_id == claim_id)
        .where(LossItem.status.notin_(RECOGNIZED_STATUSES))
        .order_by(LossItem.seq)
    ).all()
    return list(rows)


@dataclass
class ClaimMoney:
    approved_total: Decimal          # 认可损失总额
    cumulative_indemnity: Decimal    # 累计应赔额（已扣一次免赔、受上限约束）
    succeeded_total: Decimal         # 已成功支付
    reserved_total: Decimal          # 已锁定待支付 + 结果未知在途付款占用
    remaining_liability: Decimal     # 剩余合同责任 = 应赔 - 已付 - 在途占用
    deductible: Decimal
    limit_amount: Decimal


def money_snapshot(db: Session, claim: Claim) -> ClaimMoney:
    approved_total = sum((it.approved_amount for it in recognized_items(db, claim.id)), D("0"))
    raw = approved_total - claim.policy.deductible
    cumulative = max(D("0"), raw)
    cumulative = min(cumulative, claim.policy.limit_amount)

    succeeded = D("0")
    reserved = D("0")
    for p in db.scalars(select(Payment).where(Payment.claim_id == claim.id)).all():
        if p.status == PaymentStatus.SUCCEEDED:
            succeeded += p.amount
        elif p.status in RESERVING_STATUSES:
            reserved += p.amount

    remaining = max(D("0"), cumulative - succeeded - reserved)
    return ClaimMoney(
        approved_total=approved_total,
        cumulative_indemnity=cumulative,
        succeeded_total=succeeded,
        reserved_total=reserved,
        remaining_liability=remaining,
        deductible=claim.policy.deductible,
        limit_amount=claim.policy.limit_amount,
    )


def active_payments(db: Session, claim_id: int) -> list[Payment]:
    """仍占用额度的在途付款。"""
    return [
        p
        for p in db.scalars(select(Payment).where(Payment.claim_id == claim_id)).all()
        if p.status in RESERVING_STATUSES
    ]
