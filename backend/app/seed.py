"""虚构演示数据：保单（免赔 5000 / 上限 40000）、地震报案、三项损失、四个角色账号。

认可 18000、12000，第三项争议 8000（报案 10000）：
- 第三项两天后获认可时：分批先付 25000（=18000+12000-5000），再补 8000；
- 整案办理：稍后一次付 33000（=18000+12000+8000-5000，未超 40000 上限）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .enums import ItemStatus, MaterialStatus, Role
from .models import Claim, LossItem, Material, Policy, User
from .services.auth import hash_password

SEED_USERS = [
    ("reporter", "张报案", Role.REPORTER, "test1234"),
    ("surveyor", "李查勘", Role.SURVEYOR, "test1234"),
    ("adjuster", "王理算", Role.ADJUSTER, "test1234"),
    ("officer_zhao", "赵复核", Role.PAY_OFFICER, "test1234"),
    ("officer_qian", "钱复核", Role.PAY_OFFICER, "test1234"),
]


def seed_all(db: Session) -> None:
    users: dict[str, User] = {}
    for username, display, role, pwd in SEED_USERS:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is None:
            existing = User(
                username=username,
                display_name=display,
                role=role,
                password_hash=hash_password(pwd),
            )
            db.add(existing)
        users[username] = existing
    db.flush()

    if db.scalar(select(Claim).where(Claim.claim_no == "CLM-2026-1120-01")):
        db.commit()
        return

    policy = Policy(
        policy_no="POL-EQ-2026-0088",
        subject="成都市温江区柳城街道自建房（建筑主体及室内财产）",
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        deductible=5000,
        limit_amount=40000,
        payee_name="张报案",
        payee_account="6222 8888 0001 2026",
    )
    db.add(policy)
    db.flush()

    event_time = datetime(2026, 11, 20, 9, 15, tzinfo=timezone.utc)
    claim = Claim(
        claim_no="CLM-2026-1120-01",
        policy_id=policy.id,
        event_time=event_time,
        event_desc="2026-11-20 里氏 6.1 级地震，房屋墙体开裂、室内家具电器及装修受损",
    )
    db.add(claim)
    db.flush()

    items_spec = [
        {
            "title": "建筑主体墙体裂缝修复",
            "category": "building",
            "claimed": 20000,
            "status": ItemStatus.RECOGNIZED,
            "approved": 18000,
            "material": "房屋安全鉴定报告、维修报价单（3 家施工队比价）",
        },
        {
            "title": "室内家具与电器损失",
            "category": "indoor",
            "claimed": 15000,
            "status": ItemStatus.RECOGNIZED,
            "approved": 12000,
            "material": "受损家具电器照片、购买发票、残值评估单",
        },
        {
            "title": "室内吊顶与墙面装修损失",
            "category": "indoor",
            "claimed": 10000,
            "status": ItemStatus.DISPUTED,
            "approved": None,
            "material": "装修合同与付款凭证（关联性与金额待核实）",
        },
    ]
    for seq, spec in enumerate(items_spec, start=1):
        item = LossItem(
            claim_id=claim.id,
            seq=seq,
            title=spec["title"],
            category=spec["category"],
            claimed_amount=spec["claimed"],
            approved_amount=spec["approved"],
            status=spec["status"],
            revision=2 if spec["approved"] is not None else 1,
            dispute_reason=("吊顶脱落与本次地震的关联性及装修现值待补证核实，暂列争议 8000 元"
                            if spec["status"] == ItemStatus.DISPUTED else None),
        )
        db.add(item)
        db.flush()
        db.add(
            Material(
                item_id=item.id,
                status=MaterialStatus.ACCEPTED,
                request_note="报案初始材料",
                file_name=f"material-item-{seq}.zip",
                file_note=spec["material"],
                review_note="随案上传" if spec["status"] == ItemStatus.RECOGNIZED else "待查勘核实",
                requested_by_id=users["reporter"].id,
                reviewed_by_id=users["surveyor"].id,
            )
        )

    db.commit()


def reset_and_seed() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()


if __name__ == "__main__":
    reset_and_seed()
    print("种子数据已写入：保单 POL-EQ-2026-0088 / 报案 CLM-2026-1120-01 / 5 个角色账号")
