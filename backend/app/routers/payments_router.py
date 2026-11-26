from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import GatewayOutcome, Role
from ..models import User
from ..schemas import PayIn
from ..serializers import payment_out
from ..services.auth import require_roles
from ..services.payment import create_payment, query_payment

router = APIRouter(tags=["payments"])


@router.post("/batches/{batch_id}/pay")
def pay_batch(
    batch_id: int,
    body: PayIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.PAY_OFFICER)),
):
    """付款复核员发起支付，可选择支付模拟器的结果模式。"""
    payment = create_payment(db, batch_id, user, GatewayOutcome(body.gateway_outcome))
    return payment_out(payment)


@router.post("/payments/{payment_id}/query")
def query_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.PAY_OFFICER)),
):
    """查询结果未知付款的回执；不会生成新付款。"""
    payment = query_payment(db, payment_id, user)
    return payment_out(payment)
