"""和解批次：部分和解（partial，无争议项先行）与整案和解（whole_case）。

两条路径履行同一份合同责任：免赔只在事故层核算一次，批次可付额由核算引擎
统一计算（累计应赔 − 已成功支付 − 在途占用），批次本身不重复扣免赔。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import BatchStatus, Role
from ..models import BatchItem, Claim, LossItem, SettlementBatch, User
from ..schemas import BatchIn
from ..serializers import batch_out
from ..services.auth import current_user, require_roles
from ..services.calc import money_snapshot, recognized_items, unresolved_items

router = APIRouter(tags=["batches"])


def _active_batches_for_item(db: Session, item_id: int) -> list[SettlementBatch]:
    return list(
        db.scalars(
            select(SettlementBatch)
            .join(BatchItem, BatchItem.batch_id == SettlementBatch.id)
            .where(BatchItem.item_id == item_id)
            .where(SettlementBatch.status != BatchStatus.CANCELLED)
        ).all()
    )


@router.post("/claims/{claim_id}/batches", status_code=status.HTTP_201_CREATED)
def create_batch(
    claim_id: int,
    body: BatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER)),
):
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报案不存在")

    recognized = recognized_items(db, claim.id)
    rec_map = {it.id: it for it in recognized}

    if body.kind == "whole_case":
        if unresolved_items(db, claim.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "整案和解要求所有分项均有最终认可/拒绝结论，当前仍有未了结的争议项",
            )
        if any(b.status != BatchStatus.CANCELLED for b in claim.batches):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "已存在其他和解批次；部分和解之后的补差应继续使用 partial 批次",
            )
        items = recognized
    else:
        if not body.item_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "部分和解必须指定损失项目")
        items = []
        for iid in body.item_ids:
            item = rec_map.get(iid)
            if item is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"项目 #{iid} 尚未认可，不能进入和解批次（争议项须先补证/报价并接受）",
                )
            items.append(item)

    if not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有可纳入批次的认可项目")

    for item in items:
        active = _active_batches_for_item(db, item.id)
        if active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"项目 #{item.id} 已在未作废批次 #{active[0].id} 中，不能重复纳入",
            )

    snap = money_snapshot(db, claim)
    batch = SettlementBatch(
        claim_id=claim.id,
        kind=body.kind,
        status=BatchStatus.PENDING_ACCEPTANCE,
        expected_amount=snap.remaining_liability,
    )
    db.add(batch)
    db.flush()
    for item in items:
        db.add(
            BatchItem(
                batch_id=batch.id,
                item_id=item.id,
                snapshot_amount=item.approved_amount,
                snapshot_revision=item.revision,
            )
        )
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)


@router.post("/batches/{batch_id}/accept")
def accept_batch(
    batch_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REPORTER)),
):
    from datetime import datetime, timezone

    batch = db.get(SettlementBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "和解批次不存在")
    if batch.status != BatchStatus.PENDING_ACCEPTANCE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"批次当前状态为 {batch.status.value}")

    accepted = bool(payload.get("accepted", True))
    if not accepted:
        batch.status = BatchStatus.CANCELLED
        batch.cancel_reason = "报案人拒绝接受该和解批次"
        db.commit()
        return batch_out(db, batch)

    # 接受时冲突检测：批次快照修订号 vs 项目当前修订号
    conflicts = []
    for bi in batch.batch_items:
        item = db.get(LossItem, bi.item_id)
        if item.revision != bi.snapshot_revision:
            conflicts.append(
                {
                    "item_id": item.id,
                    "item_title": item.title,
                    "snapshot_amount": str(bi.snapshot_amount),
                    "snapshot_revision": bi.snapshot_revision,
                    "current_revision": item.revision,
                    "current_approved_amount": str(item.approved_amount),
                }
            )
    if conflicts:
        batch.status = BatchStatus.CANCELLED
        batch.cancel_reason = "接受时检测到认可金额修订冲突，批次作废，须按最新金额重建"
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "批次金额已过期（认可金额在接受期间变化），批次已作废", "conflicts": conflicts},
        )

    if batch.kind == "whole_case" and unresolved_items(db, batch.claim_id):
        batch.status = BatchStatus.CANCELLED
        batch.cancel_reason = "整案接受时出现未了结项目"
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "整案批次接受时仍存在未了结项目，已作废")

    batch.status = BatchStatus.ACCEPTED
    batch.accepted_at = datetime.now(timezone.utc)
    # 接受时刷新预期可付额（实际支付时仍会再次核算）
    batch.expected_amount = money_snapshot(db, batch.claim).remaining_liability
    db.commit()
    db.refresh(batch)
    return batch_out(db, batch)


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    batch = db.get(SettlementBatch, batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "和解批次不存在")
    return batch_out(db, batch)
