"""理算员报价与报案人接受/拒绝。

报价绑定具体项目及材料修订快照（snapshot_revision）；接受期间若认可金额变化
（修订号推进），接受动作返回可见冲突并将报价置为 conflicted，不允许按旧报价成交。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import ItemStatus, OfferStatus, Role
from ..models import LossItem, Offer, OfferItem, User
from ..schemas import OfferIn
from ..serializers import offer_out
from ..services.auth import current_user, require_roles

router = APIRouter(prefix="/offers", tags=["offers"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_offer(
    body: OfferIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER)),
):
    if not body.item_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "报价必须绑定至少一个损失项目")
    items: list[LossItem] = []
    for item_id in body.item_ids:
        item = db.get(LossItem, item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"损失项目 #{item_id} 不存在")
        if item.status != ItemStatus.DISPUTED:
            raise HTTPException(status.HTTP_409_CONFLICT, f"项目 #{item_id} 不是争议项，无需报价")
        items.append(item)

    offer = Offer(
        claim_id=items[0].claim_id,
        status=OfferStatus.OPEN,
        note=body.note,
        created_by_id=user.id,
    )
    db.add(offer)
    db.flush()
    for item in items:
        db.add(
            OfferItem(
                offer_id=offer.id,
                item_id=item.id,
                quoted_amount=item.claimed_amount,  # 默认按报案金额报价，理算员可在后续版本调整
                snapshot_amount=item.approved_amount,
                snapshot_revision=item.revision,
            )
        )
    db.commit()
    db.refresh(offer)
    return offer_out(db, offer)


@router.post("/{offer_id}/quoted-amount")
def update_quoted_amount(
    offer_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER)),
):
    """调整报价中某项目的报价金额（仅 OPEN 报价可改）。"""
    from decimal import Decimal

    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报价不存在")
    if offer.status != OfferStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅待接受的报价可以调整")
    oi = next((x for x in offer.offer_items if x.item_id == payload.get("item_id")), None)
    if oi is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报价内不存在该项目")
    oi.quoted_amount = Decimal(str(payload["quoted_amount"]))
    db.commit()
    return offer_out(db, offer)


def _conflict_check(db: Session, offer: Offer) -> list[dict]:
    conflicts = []
    for oi in offer.offer_items:
        item = db.get(LossItem, oi.item_id)
        if item.revision != oi.snapshot_revision:
            conflicts.append(
                {
                    "item_id": item.id,
                    "item_title": item.title,
                    "quoted_amount": str(oi.quoted_amount),
                    "snapshot_revision": oi.snapshot_revision,
                    "current_revision": item.revision,
                    "current_approved_amount": str(item.approved_amount)
                    if item.approved_amount is not None
                    else None,
                    "reason": "接受期间认可金额/材料已发生修订，旧报价失效",
                }
            )
    return conflicts


@router.post("/{offer_id}/accept")
def accept_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REPORTER)),
):
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报价不存在")
    if offer.status != OfferStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"报价当前状态为 {offer.status.value}，不能接受")

    conflicts = _conflict_check(db, offer)
    if conflicts:
        offer.status = OfferStatus.CONFLICTED
        offer.conflict_note = "接受时检测到项目修订冲突：" + "；".join(
            f"项目{c['item_id']}修订号 {c['snapshot_revision']}→{c['current_revision']}" for c in conflicts
        )
        from datetime import datetime, timezone

        offer.decided_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "报价与当前认可金额冲突，已失效，请基于最新结论重新报价", "conflicts": conflicts},
        )

    from datetime import datetime, timezone

    for oi in offer.offer_items:
        item = db.get(LossItem, oi.item_id)
        # 接受报价 → 报价金额成为该项目的认可金额
        if item.approved_amount != oi.quoted_amount:
            item.revision += 1
        item.approved_amount = oi.quoted_amount
        item.status = ItemStatus.RECOGNIZED_AFTER_DISPUTE
        item.dispute_reason = None
    offer.status = OfferStatus.ACCEPTED
    offer.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(offer)
    return offer_out(db, offer)


@router.post("/{offer_id}/reject")
def reject_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REPORTER)),
):
    from datetime import datetime, timezone

    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报价不存在")
    if offer.status != OfferStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"报价当前状态为 {offer.status.value}")
    offer.status = OfferStatus.REJECTED
    offer.decided_at = datetime.now(timezone.utc)
    db.commit()
    return offer_out(db, offer)
