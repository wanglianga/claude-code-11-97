from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str


class PolicyOut(BaseModel):
    id: int
    policy_no: str
    subject: str
    coverage_start: date
    coverage_end: date
    deductible: Decimal
    limit_amount: Decimal
    payee_name: str
    payee_account: str


class ClaimSummary(BaseModel):
    id: int
    claim_no: str
    policy: PolicyOut
    event_time: datetime
    event_desc: str


class MaterialIn(BaseModel):
    file_name: str
    file_note: str = ""


class MaterialRequestIn(BaseModel):
    request_note: str


class MaterialReviewIn(BaseModel):
    accept: bool
    review_note: str = ""


class SurveyIn(BaseModel):
    # 认可金额；为空表示该项目有争议（转入 disputed）
    approved_amount: Decimal | None = Field(default=None, ge=0)
    dispute_reason: str | None = None


class MaterialCreateIn(BaseModel):
    """报案人新增损失项目及材料。"""

    title: str
    category: Literal["building", "indoor"]
    claimed_amount: Decimal = Field(ge=0)
    file_name: str
    file_note: str = ""


class OfferItemIn(BaseModel):
    item_id: int
    quoted_amount: Decimal = Field(ge=0)


class OfferIn(BaseModel):
    item_ids: list[int]
    note: str = ""


class BatchIn(BaseModel):
    kind: Literal["partial", "whole_case"]
    item_ids: list[int] | None = None  # partial 时指定项目；whole_case 自动纳入全部已认可项目


class AcceptIn(BaseModel):
    accepted: bool


class PayIn(BaseModel):
    gateway_outcome: Literal["success", "success_receipt_lost", "late_success", "decline"]


class CorrectionIn(BaseModel):
    item_id: int
    payment_id: int
    reason: str


class CorrectionProcessIn(BaseModel):
    process_note: str


TokenOut.model_rebuild()
