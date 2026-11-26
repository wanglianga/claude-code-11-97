from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import (
    BatchStatus,
    CorrectionStatus,
    ItemStatus,
    MaterialStatus,
    OfferStatus,
    PaymentStatus,
    Role,
)


def pg_enum(py_enum, type_name: str) -> SAEnum:
    """PG 枚举类型统一存储枚举的 value（小写），与 API 取值一致。"""
    return SAEnum(
        py_enum,
        name=type_name,
        values_callable=lambda members: [m.value for m in members],
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[Role] = mapped_column(pg_enum(Role, "user_role"))

    api_tokens: Mapped[list["ApiToken"]] = relationship(back_populates="user")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="api_tokens")


class Policy(Base):
    """保单：保险标的、保障起止、事故免赔额、事故赔偿上限、收款人。"""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(255))  # 保险标的
    coverage_start: Mapped[date] = mapped_column(Date)
    coverage_end: Mapped[date] = mapped_column(Date)
    deductible: Mapped[Decimal] = mapped_column(Numeric(12, 2))   # 事故免赔额（一次事故共享一次）
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # 事故赔偿上限
    payee_name: Mapped[str] = mapped_column(String(64))
    payee_account: Mapped[str] = mapped_column(String(64))

    claims: Mapped[list["Claim"]] = relationship(back_populates="policy")


class Claim(Base):
    """一次地震事故的报案（同一保单项下一次事故共享免赔与上限）。"""

    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_desc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    policy: Mapped[Policy] = relationship(back_populates="claims")
    items: Mapped[list["LossItem"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="LossItem.seq"
    )
    batches: Mapped[list["SettlementBatch"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="SettlementBatch.id"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Payment.id"
    )


class LossItem(Base):
    """分项损失（建筑 / 室内财产可分项查勘）。revision 在每次金额或材料修订时递增，用于报价冲突检测。"""

    __tablename__ = "loss_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))  # building / indoor
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[ItemStatus] = mapped_column(pg_enum(ItemStatus, "item_status"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship(back_populates="items")
    materials: Mapped[list["Material"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="Material.id"
    )

    __table_args__ = (UniqueConstraint("claim_id", "seq", name="uq_loss_item_seq"),)


class Material(Base):
    """补证请求与材料修订记录。"""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("loss_items.id", ondelete="CASCADE"), index=True)
    status: Mapped[MaterialStatus] = mapped_column(pg_enum(MaterialStatus, "material_status"))
    request_note: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    item: Mapped[LossItem] = relationship(back_populates="materials")


class Offer(Base):
    """理算员就争议项目提出的报价，绑定具体项目及材料修订快照。"""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    status: Mapped[OfferStatus] = mapped_column(pg_enum(OfferStatus, "offer_status"))
    note: Mapped[str] = mapped_column(Text, default="")
    conflict_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    offer_items: Mapped[list["OfferItem"]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )


class OfferItem(Base):
    __tablename__ = "offer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("loss_items.id"))
    quoted_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    snapshot_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    snapshot_revision: Mapped[int] = mapped_column(Integer)

    offer: Mapped[Offer] = relationship(back_populates="offer_items")


class SettlementBatch(Base):
    """和解批次：无争议先行的部分和解（partial）或整案和解（whole_case）。"""

    __tablename__ = "settlement_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # partial / whole_case
    status: Mapped[BatchStatus] = mapped_column(pg_enum(BatchStatus, "batch_status"))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0")
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship(back_populates="batches")
    batch_items: Mapped[list["BatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="Payment.id"
    )


class BatchItem(Base):
    __tablename__ = "batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("settlement_batches.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("loss_items.id"))
    snapshot_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # 接受时的认可金额快照
    snapshot_revision: Mapped[int] = mapped_column(Integer)            # 接受时的项目修订号快照

    batch: Mapped[SettlementBatch] = relationship(back_populates="batch_items")


class Payment(Base):
    """一笔付款。LOCKED / 结果未知状态均占用事故额度；超时不重新生成新付款，只能查询回执。"""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("settlement_batches.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[PaymentStatus] = mapped_column(pg_enum(PaymentStatus, "payment_status"))
    gateway_outcome: Mapped[str] = mapped_column(String(40))  # 模拟器选择的结果模式
    gateway_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poll_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    last_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    claim: Mapped[Claim] = relationship(back_populates="payments")
    batch: Mapped[SettlementBatch] = relationship(back_populates="payments")
    events: Mapped[list["PaymentEvent"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", order_by="PaymentEvent.id"
    )


class PaymentEvent(Base):
    """付款过程审计轨迹（提交、回执丢失、查询、成功、拒绝）。"""

    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    payment: Mapped[Payment] = relationship(back_populates="events")


class CorrectionCase(Base):
    """已付款项目再发现错误时的人工更正案件；不静默修改历史付款。"""

    __tablename__ = "correction_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("loss_items.id"))
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    status: Mapped[CorrectionStatus] = mapped_column(
        pg_enum(CorrectionStatus, "correction_status"),
        default=CorrectionStatus.OPEN,
        server_default=CorrectionStatus.OPEN.value,
    )
    reason: Mapped[str] = mapped_column(Text)
    process_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    processed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
