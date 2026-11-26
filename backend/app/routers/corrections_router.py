"""人工更正案件。

已付款项目再发现错误时，不得静默修改历史付款，只能建立人工更正案件，
由付款复核员登记处理结论。历史 Payment 记录保持不变，审计轨迹完整保留。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import BatchStatus, CorrectionStatus, PaymentStatus, Role
from ..models import BatchItem, CorrectionCase, LossItem, Payment, SettlementBatch, User
from ..schemas import CorrectionIn, CorrectionProcessIn
from ..serializers import correction_out
from ..services.auth import require_roles

router = APIRouter(tags=["corrections"])


def _payment_contains_item(db: Session, payment: Payment, item_id: int) -> bool:
    return (
        db.query(BatchItem)
        .filter(
            BatchItem.batch_id == payment.batch_id,
            BatchItem.item_id == item_id,
        )
        .first()
        is not None
    )


@router.post("/claims/{claim_id}/corrections", status_code=status.HTTP_201_CREATED)
def open_correction(
    claim_id: int,
    body: CorrectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.SURVEYOR, Role.ADJUSTER, Role.PAY_OFFICER)),
):
    item = db.get(LossItem, body.item_id)
    if item is None or item.claim_id != claim_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "损失项目不存在或不属于该报案")
    payment = db.get(Payment, body.payment_id)
    if payment is None or payment.claim_id != claim_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "付款不存在或不属于该报案")
    if payment.status != PaymentStatus.SUCCEEDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅支付成功的历史付款需要人工更正")
    if not _payment_contains_item(db, payment, body.item_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "该付款不包含所选损失项目")
    if not body.reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须填写更正原因")

    case = CorrectionCase(
        claim_id=claim_id,
        item_id=body.item_id,
        payment_id=body.payment_id,
        reason=body.reason,
        opened_by_id=user.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return correction_out(db, case)


@router.post("/corrections/{case_id}/process")
def process_correction(
    case_id: int,
    body: CorrectionProcessIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.PAY_OFFICER)),
):
    from datetime import datetime, timezone

    case = db.get(CorrectionCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "更正案件不存在")
    if case.status.value == "processed":
        raise HTTPException(status.HTTP_409_CONFLICT, "更正案件已处理")
    case.status = CorrectionStatus.PROCESSED
    case.process_note = body.process_note or "人工复核完成，历史付款记录保持不变"
    case.processed_by_id = user.id
    case.processed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)
    return correction_out(db, case)


@router.get("/claims/{claim_id}/corrections")
def list_corrections(
    claim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.SURVEYOR, Role.ADJUSTER, Role.PAY_OFFICER, Role.REPORTER)),
):
    rows = db.scalars(
        select(CorrectionCase)
        .where(CorrectionCase.claim_id == claim_id)
        .order_by(CorrectionCase.id)
    ).all()
    return [correction_out(db, c) for c in rows]
