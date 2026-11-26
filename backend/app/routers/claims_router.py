from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import ItemStatus, MaterialStatus, Role
from ..models import BatchItem, Claim, LossItem, Material, SettlementBatch, User
from ..schemas import MaterialCreateIn, MaterialRequestIn, MaterialReviewIn, MaterialIn, SurveyIn
from ..serializers import claim_detail, item_out
from ..services.auth import current_user, require_roles

router = APIRouter(tags=["claims"])


def _get_claim(db: Session, claim_id: int) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报案不存在")
    return claim


def _get_item(db: Session, item_id: int) -> LossItem:
    item = db.get(LossItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "损失项目不存在")
    return item


def _item_locked_batches(db: Session, item_id: int) -> list[SettlementBatch]:
    """项目所在的、未作废的和解批次。"""
    rows = db.scalars(
        select(SettlementBatch)
        .join(BatchItem, BatchItem.batch_id == SettlementBatch.id)
        .where(BatchItem.item_id == item_id)
        .where(SettlementBatch.status != "cancelled")
    ).all()
    return list(rows)


def _item_in_paid_batch(db: Session, item_id: int) -> bool:
    from ..enums import BatchStatus

    rows = db.scalars(
        select(SettlementBatch)
        .join(BatchItem, BatchItem.batch_id == SettlementBatch.id)
        .where(BatchItem.item_id == item_id)
        .where(SettlementBatch.status == BatchStatus.PAID)
    ).all()
    return len(rows) > 0


@router.get("/claims")
def list_claims(db: Session = Depends(get_db), user: User = Depends(current_user)):
    claims = db.scalars(select(Claim).order_by(Claim.id)).all()
    return [
        {
            "id": c.id,
            "claim_no": c.claim_no,
            "policy_no": c.policy.policy_no,
            "event_desc": c.event_desc,
            "event_time": c.event_time.isoformat(),
        }
        for c in claims
    ]


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return claim_detail(db, _get_claim(db, claim_id))


@router.post("/claims/{claim_id}/items", status_code=status.HTTP_201_CREATED)
def add_loss_item(
    claim_id: int,
    body: MaterialCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REPORTER)),
):
    """报案人上传损失项目及材料。"""
    claim = _get_claim(db, claim_id)
    max_seq = max((it.seq for it in claim.items), default=0)
    item = LossItem(
        claim_id=claim.id,
        seq=max_seq + 1,
        title=body.title,
        category=body.category,
        claimed_amount=body.claimed_amount,
        status=ItemStatus.SUBMITTED,
    )
    db.add(item)
    db.flush()
    db.add(
        Material(
            item_id=item.id,
            status=MaterialStatus.ACCEPTED,
            request_note="报案初始材料",
            file_name=body.file_name,
            file_note=body.file_note,
            requested_by_id=user.id,
            review_note="随案上传",
            reviewed_by_id=user.id,
        )
    )
    db.commit()
    db.refresh(item)
    return item_out(db, item)


@router.post("/items/{item_id}/survey")
def survey_item(
    item_id: int,
    body: SurveyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.SURVEYOR)),
):
    """查勘员确认属于本次事故的损坏与认可金额；不认可金额则列为争议项。

    已进入未作废批次或已付款的项目被锁定：已付款项目只能走人工更正案件。
    """
    item = _get_item(db, item_id)
    # 已付款项目最优先拦截：历史付款不得静默修改
    if _item_in_paid_batch(db, item.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该项目已在支付成功的批次中，历史付款不得静默修改；如发现错误请建立人工更正案件",
        )
    active = _item_locked_batches(db, item.id)
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该项目已纳入和解批次 #{active[0].id}，须先作废批次或完成付款后再处理",
        )

    if body.approved_amount is not None:
        if item.approved_amount != body.approved_amount:
            item.revision += 1  # 认可金额变化 → 修订号递增，供报价/批次接受时做冲突检测
        item.approved_amount = body.approved_amount
        item.status = (
            ItemStatus.RECOGNIZED_AFTER_DISPUTE
            if item.status == ItemStatus.DISPUTED
            else ItemStatus.RECOGNIZED
        )
        item.dispute_reason = None
    else:
        if not body.dispute_reason:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "列为争议项必须填写争议原因")
        item.status = ItemStatus.DISPUTED
        item.dispute_reason = body.dispute_reason
        item.revision += 1
    db.commit()
    db.refresh(item)
    return item_out(db, item)


@router.post("/items/{item_id}/material-request", status_code=status.HTTP_201_CREATED)
def request_material(
    item_id: int,
    body: MaterialRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER)),
):
    """理算员就争议项目要求补证。"""
    item = _get_item(db, item_id)
    if item.status != ItemStatus.DISPUTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅争议项目可以发起补证请求")
    m = Material(
        item_id=item.id,
        status=MaterialStatus.PENDING,
        request_note=body.request_note,
        requested_by_id=user.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"id": m.id, "status": m.status.value}


@router.post("/materials/{material_id}/submit")
def submit_material(
    material_id: int,
    body: MaterialIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.REPORTER)),
):
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "补证记录不存在")
    if m.status != MaterialStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "该补证请求已提交或已审核")
    m.status = MaterialStatus.SUBMITTED
    m.file_name = body.file_name
    m.file_note = body.file_note
    from datetime import datetime, timezone

    m.submitted_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": m.id, "status": m.status.value}


@router.post("/materials/{material_id}/review")
def review_material(
    material_id: int,
    body: MaterialReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER)),
):
    """理算员审核补交材料：通过则按审核结论认可该争议项（材料修订同样推进项目修订号）。"""
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "补证记录不存在")
    if m.status != MaterialStatus.SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅已提交待审核的材料可以审核")
    item = _get_item(db, m.item_id)
    m.review_note = body.review_note
    m.reviewed_by_id = user.id
    if body.accept:
        m.status = MaterialStatus.ACCEPTED
        item.status = ItemStatus.RECOGNIZED_AFTER_DISPUTE
        if item.approved_amount is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "审核通过前须先由查勘/理算给出认可金额")
        item.revision += 1  # 材料修订落地，绑定该修订的旧报价将可见冲突
    else:
        m.status = MaterialStatus.REJECTED
    db.commit()
    db.refresh(item)
    return item_out(db, item)


@router.post("/items/{item_id}/recognize")
def recognize_after_dispute(
    item_id: int,
    body: SurveyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADJUSTER, Role.SURVEYOR)),
):
    """争议项补证后给予认可金额（题设“第三项两天后获认可”）。"""
    item = _get_item(db, item_id)
    if item.status != ItemStatus.DISPUTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅争议项目可以使用争议后认可")
    if body.approved_amount is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "认可必须给出认可金额")
    if _item_in_paid_batch(db, item.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "已付款项目只能建立人工更正案件")
    if _item_locked_batches(db, item.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "项目已在未作废批次中，无法改变认可金额")
    if item.approved_amount != body.approved_amount:
        item.revision += 1
    item.approved_amount = body.approved_amount
    item.status = ItemStatus.RECOGNIZED_AFTER_DISPUTE
    item.dispute_reason = None
    db.commit()
    db.refresh(item)
    return item_out(db, item)
