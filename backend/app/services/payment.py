"""付款领域服务：行锁串行化、额度占用、网关异常处理。

关键纪律：
- 提交即对报案行加 FOR UPDATE 行锁，两名复核员同时付款时第二笔会被拒绝（不会重复出款）；
- 超时 / 回执丢失 ≠ 失败：付款保留为结果未知并继续占用事故额度，只能查询，不得重新生成；
- 明确拒绝（declined）不占额度，可在同批次重新发起一笔新付款；
- 可付额始终由核算引擎实时计算：累计应赔 − 已成功 − 在途占用。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import BatchStatus, GatewayOutcome, PaymentStatus
from ..models import Claim, Payment, PaymentEvent, SettlementBatch, User
from .calc import money_snapshot
from .gateway import GatewayError, ReceiptLost, gateway


def _add_event(payment: Payment, event_type: str, detail: str) -> None:
    payment.events.append(PaymentEvent(event_type=event_type, detail=detail))


def _refresh_batch_state(db: Session, batch: SettlementBatch) -> None:
    # 显式查询而非依赖关系集合（新建对象在 flush 后未必出现在 batch.payments 中）
    db.flush()  # autoflush=False：先把付款状态变更刷入，查询才能读到终态
    succeeded = db.scalar(
        select(Payment.id).where(
            Payment.batch_id == batch.id,
            Payment.status == PaymentStatus.SUCCEEDED,
        ).limit(1)
    )
    if succeeded is not None:
        batch.status = BatchStatus.PAID


def create_payment(
    db: Session, batch_id: int, reviewer: User, outcome: GatewayOutcome
) -> Payment:
    # 1) 锁定报案行，串行化同一事故的付款发起
    batch = db.get(SettlementBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "和解批次不存在")
    claim = db.scalar(select(Claim).where(Claim.id == batch.claim_id).with_for_update())

    if batch.status not in (BatchStatus.ACCEPTED,):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"批次状态为 {batch.status.value}，仅已接受待付款的批次可以发起支付",
        )

    # 2) 幂等：已有在途付款（含结果未知）时拒绝重复生成
    in_flight = [
        p
        for p in batch.payments
        if p.status
        in (
            PaymentStatus.LOCKED,
            PaymentStatus.SUBMITTED_UNKNOWN,
            PaymentStatus.TIMED_OUT,
        )
    ]
    if in_flight:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"批次已有在途付款 #{in_flight[0].id}（状态 {in_flight[0].status.value}），"
            "须先查询回执，禁止重复发起付款",
        )

    # 3) 实时核算可付额（扣减已成功支付与在途占用）
    snap = money_snapshot(db, claim)
    if snap.remaining_liability <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"事故剩余责任为 0（累计应赔 {snap.cumulative_indemnity}，"
            f"已成功 {snap.succeeded_total}，在途占用 {snap.reserved_total}），无可付金额",
        )

    payment = Payment(
        claim_id=claim.id,
        batch_id=batch.id,
        amount=snap.remaining_liability,
        status=PaymentStatus.LOCKED,
        gateway_outcome=outcome.value,
        gateway_ref=gateway.new_ref(),
        reviewer_id=reviewer.id,
        last_note="付款已锁定待支付，已占用事故额度",
    )
    _add_event(payment, "locked", f"复核员 {reviewer.username} 锁定付款，金额 {payment.amount}")
    db.add(payment)
    db.flush()

    # 4) 调用模拟网关；网络类异常必须落库为“结果未知”，而不是丢弃这笔付款
    try:
        gateway.submit(payment.gateway_ref, str(payment.amount), outcome)
    except ReceiptLost as exc:
        payment.status = PaymentStatus.SUBMITTED_UNKNOWN
        payment.last_note = "网关已扣款但响应丢失，结果未知，待查询回执"
        _add_event(payment, "receipt_lost", str(exc))
        db.commit()
        db.refresh(payment)
        return payment
    except GatewayError as exc:  # SubmitTimeout
        payment.status = PaymentStatus.TIMED_OUT
        payment.last_note = "提交超时，网关侧可能已受理，只能凭交易号查询，禁止重新发起"
        _add_event(payment, "submit_timeout", str(exc))
        db.commit()
        db.refresh(payment)
        return payment

    # 即时得到终态
    if outcome == GatewayOutcome.SUCCESS:
        payment.status = PaymentStatus.SUCCEEDED
        payment.last_note = "支付成功，回执已收到"
        _add_event(payment, "succeeded", f"网关即时返回成功回执，交易号 {payment.gateway_ref}")
        _refresh_batch_state(db, batch)
    else:  # DECLINE
        payment.status = PaymentStatus.DECLINED
        payment.last_note = "网关明确拒绝，本笔不占用额度，可重新发起付款"
        _add_event(payment, "declined", f"网关拒绝交易 {payment.gateway_ref}")
    db.commit()
    db.refresh(payment)
    return payment


def query_payment(db: Session, payment_id: int, reviewer: User) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "付款不存在")
    if payment.status not in (
        PaymentStatus.SUBMITTED_UNKNOWN,
        PaymentStatus.TIMED_OUT,
        PaymentStatus.LOCKED,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"付款状态为 {payment.status.value}，已是终态或无需查询",
        )

    payment.poll_count += 1
    try:
        result = gateway.query(payment.gateway_ref)
    except KeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "网关无此交易记录，须人工核查")

    if result == PaymentStatus.SUCCEEDED:
        payment.status = PaymentStatus.SUCCEEDED
        payment.last_note = f"第 {payment.poll_count} 次查询取得成功回执"
        _add_event(payment, "query_succeeded", f"第 {payment.poll_count} 次查询：网关确认成功")
        _refresh_batch_state(db, payment.batch)
    elif result == PaymentStatus.DECLINED:
        payment.status = PaymentStatus.DECLINED
        payment.last_note = f"第 {payment.poll_count} 次查询确认网关拒绝"
        _add_event(payment, "query_declined", f"第 {payment.poll_count} 次查询：网关确认拒绝")
    else:
        payment.status = PaymentStatus.SUBMITTED_UNKNOWN
        payment.last_note = f"第 {payment.poll_count} 次查询仍处理中，继续占用额度"
        _add_event(payment, "query_pending", f"第 {payment.poll_count} 次查询：处理中/结果未知")
    db.commit()
    db.refresh(payment)
    return payment
