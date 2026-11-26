"""端到端业务场景：分批和解、整案和解、争议未认可、报价冲突、人工更正。"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LossItem, Offer


def claim_money(client, auth):
    return client.get("/claims/1", headers=auth["reporter"]).json()["money"]


def resolve_item3(client, auth, amount: str = "8000.00") -> int:
    """模拟“两天后第三项获认可”：补证 → 提交 → 认可 → 审核通过。返回材料 id。"""
    r = client.post(
        "/items/3/material-request",
        json={"request_note": "请补充吊顶脱落与地震关联性及装修现值凭证"},
        headers=auth["adjuster"],
    )
    assert r.status_code == 201, r.text
    material_id = r.json()["id"]
    r = client.post(
        f"/materials/{material_id}/submit",
        json={"file_name": "ceiling-proof.pdf", "file_note": "装修合同、付款流水、现场照片"},
        headers=auth["reporter"],
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/items/3/recognize",
        json={"approved_amount": amount},
        headers=auth["surveyor"],
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/materials/{material_id}/review",
        json={"accept": True, "review_note": "凭证充分，按 8000 元认可"},
        headers=auth["adjuster"],
    )
    assert r.status_code == 200, r.text
    return material_id


def partial_batch(client, auth, item_ids):
    r = client.post(
        "/claims/1/batches",
        json={"kind": "partial", "item_ids": item_ids},
        headers=auth["adjuster"],
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def accept_batch(client, auth, batch_id, accepted=True):
    return client.post(f"/batches/{batch_id}/accept", json={"accepted": accepted}, headers=auth["reporter"])


def pay(client, auth, batch_id, outcome="success", officer="zhao"):
    return client.post(
        f"/batches/{batch_id}/pay",
        json={"gateway_outcome": outcome},
        headers=auth[officer],
    )


def test_partial_settlement_pays_25000_then_8000(client, auth):
    """分批路径：无争议两项先付 25000，第三项两天后认可再补 8000，累计 33000。"""
    money = claim_money(client, auth)
    assert money["approved_total"] == "30000.00"
    assert money["cumulative_indemnity"] == "25000.00"  # 30000 - 5000 免赔
    assert money["remaining_liability"] == "25000.00"

    bid1 = partial_batch(client, auth, [1, 2])
    r = accept_batch(client, auth, bid1)
    assert r.status_code == 200, r.text
    r = pay(client, auth, bid1)
    assert r.status_code == 200, r.text
    p1 = r.json()
    assert p1["amount"] == "25000.00"
    assert p1["status"] == "succeeded"

    money = claim_money(client, auth)
    assert money["succeeded_total"] == "25000.00"
    # 已付完当前应赔，剩余责任为 0（争议项尚未认可，不产生责任）
    assert money["remaining_liability"] == "0.00"

    # 两天后第三项获认可
    resolve_item3(client, auth)
    money = claim_money(client, auth)
    assert money["approved_total"] == "38000.00"
    assert money["cumulative_indemnity"] == "33000.00"  # 免赔只扣一次：38000-5000
    assert money["remaining_liability"] == "8000.00"

    bid2 = partial_batch(client, auth, [3])
    accept_batch(client, auth, bid2)
    r = pay(client, auth, bid2)
    assert r.status_code == 200, r.text
    p2 = r.json()
    assert p2["amount"] == "8000.00"  # 补差未再扣免赔（若重复扣会是 3000）

    money = claim_money(client, auth)
    assert money["succeeded_total"] == "33000.00"
    assert money["remaining_liability"] == "0.00"

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["progress"]["stage"] == "completed"
    # 项目归属：两批分别包含 {1,2} 与 {3}
    batches = sorted(detail["batches"], key=lambda b: b["id"])
    assert sorted(i["item_id"] for i in batches[0]["items"]) == [1, 2]
    assert sorted(i["item_id"] for i in batches[1]["items"]) == [3]


def test_whole_case_pays_33000_once(client, auth):
    """整案路径：争议项了结后一次付 33000；未了结时禁止整案和解。"""
    r = client.post(
        "/claims/1/batches", json={"kind": "whole_case"}, headers=auth["adjuster"]
    )
    assert r.status_code == 409  # 争议项未了结

    resolve_item3(client, auth)
    r = client.post(
        "/claims/1/batches", json={"kind": "whole_case"}, headers=auth["adjuster"]
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    assert r.json()["kind"] == "whole_case"
    r = accept_batch(client, auth, bid)
    assert r.status_code == 200, r.text
    r = pay(client, auth, bid)
    assert r.status_code == 200, r.text
    payment = r.json()
    assert payment["amount"] == "33000.00"
    assert payment["status"] == "succeeded"

    money = claim_money(client, auth)
    assert money["succeeded_total"] == "33000.00"
    assert money["remaining_liability"] == "0.00"
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert len([p for p in detail["payments"] if p["status"] == "succeeded"]) == 1


def test_disputed_item_never_recognized(client, auth):
    """第三项始终未认可：只能先付无争议 25000，整案和解持续被阻塞。"""
    bid = partial_batch(client, auth, [1, 2])
    accept_batch(client, auth, bid)
    r = pay(client, auth, bid)
    assert r.status_code == 200
    assert r.json()["amount"] == "25000.00"

    # 整案和解仍被未了结争议项阻塞
    r = client.post(
        "/claims/1/batches", json={"kind": "whole_case"}, headers=auth["adjuster"]
    )
    assert r.status_code == 409
    # 争议项不能进入部分批次
    r = client.post(
        "/claims/1/batches", json={"kind": "partial", "item_ids": [3]}, headers=auth["adjuster"]
    )
    assert r.status_code == 409

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["progress"]["stage"] == "in_progress"
    assert any("争议" in b or "未了结" in b for b in detail["progress"]["blockers"])
    money = detail["money"]
    assert money["cumulative_indemnity"] == "25000.00"
    assert money["remaining_liability"] == "0.00"
    assert 3 in detail["unresolved_item_ids"]


def test_stale_offer_returns_visible_conflict(client, auth):
    """接受旧报价：报价绑定修订快照，认可金额变化后接受返回可见冲突。"""
    r = client.post("/offers", json={"item_ids": [3], "note": "拟按报价和解"}, headers=auth["adjuster"])
    assert r.status_code == 201, r.text
    offer_id = r.json()["id"]
    r = client.post(
        f"/offers/{offer_id}/quoted-amount",
        json={"item_id": 3, "quoted_amount": "9000.00"},
        headers=auth["adjuster"],
    )
    assert r.status_code == 200, r.text

    # 接受期间，查勘员把第三项认可为 8000，修订号推进
    r = client.post("/items/3/recognize", json={"approved_amount": "8000.00"}, headers=auth["surveyor"])
    assert r.status_code == 200, r.text

    r = client.post(f"/offers/{offer_id}/accept", headers=auth["reporter"])
    assert r.status_code == 409
    payload = r.json()["detail"] if "detail" in r.json() else r.json()
    # FastAPI 把 HTTPException(detail=dict) 放在 detail 字段
    conflicts = payload["conflicts"]
    assert conflicts[0]["item_id"] == 3
    assert conflicts[0]["current_revision"] > conflicts[0]["snapshot_revision"]

    db = SessionLocal()
    try:
        offer = db.get(Offer, offer_id)
        assert offer.status.value == "conflicted"
        assert offer.conflict_note
    finally:
        db.close()


def test_stale_batch_accept_conflicts_and_is_cancelled(client, auth):
    """批次接受期间认可金额变化：接受返回冲突，批次作废且须重建。"""
    bid = partial_batch(client, auth, [1, 2])

    db = SessionLocal()
    try:
        item = db.scalar(select(LossItem).where(LossItem.id == 1))
        item.revision += 1  # 模拟接受期间的金额修订
        db.commit()
    finally:
        db.close()

    r = accept_batch(client, auth, bid)
    assert r.status_code == 409
    detail = client.get(f"/batches/{bid}", headers=auth["reporter"]).json()
    assert detail["status"] == "cancelled"
    assert "冲突" in detail["cancel_reason"]

    # 作废后可按最新金额重建
    bid_new = partial_batch(client, auth, [1, 2])
    r = accept_batch(client, auth, bid_new)
    assert r.status_code == 200


def test_offer_acceptance_sets_recognized_amount(client, auth):
    """报价被接受后，报价金额成为认可金额，可进入整案和解。"""
    r = client.post("/offers", json={"item_ids": [3]}, headers=auth["adjuster"])
    offer_id = r.json()["id"]
    r = client.post(
        f"/offers/{offer_id}/quoted-amount",
        json={"item_id": 3, "quoted_amount": "8000.00"},
        headers=auth["adjuster"],
    )
    assert r.status_code == 200
    r = client.post(f"/offers/{offer_id}/accept", headers=auth["reporter"])
    assert r.status_code == 200, r.text

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    item3 = next(i for i in detail["items"] if i["id"] == 3)
    assert item3["approved_amount"] == "8000.00"
    assert item3["status"] == "recognized_after_dispute"

    r = client.post(
        "/claims/1/batches", json={"kind": "whole_case"}, headers=auth["adjuster"]
    )
    assert r.status_code == 201


def test_paid_item_can_only_be_corrected_manually(client, auth):
    """已付款项目再发现错误：禁止静默修改，只能建立人工更正案件。"""
    bid = partial_batch(client, auth, [1, 2])
    accept_batch(client, auth, bid)
    payment = pay(client, auth, bid).json()

    r = client.post(
        "/items/1/survey",
        json={"approved_amount": "17000.00"},
        headers=auth["surveyor"],
    )
    assert r.status_code == 409
    assert "人工更正" in r.json()["detail"]

    r = client.post(
        "/claims/1/corrections",
        json={"item_id": 1, "payment_id": payment["id"], "reason": "复核发现墙体修复面积多估 1000 元"},
        headers=auth["surveyor"],
    )
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    r = client.post(
        f"/corrections/{case_id}/process",
        json={"process_note": "人工核查属实，后续追偿流程另行登记，历史付款保持不变"},
        headers=auth["zhao"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "processed"

    # 历史付款原样保留
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    hist = next(p for p in detail["payments"] if p["id"] == payment["id"])
    assert hist["amount"] == "25000.00"
    assert hist["status"] == "succeeded"
    assert len(detail["corrections"]) == 1


def test_role_permissions_are_enforced(client, auth):
    # 报案人不能查勘
    r = client.post(
        "/items/1/survey", json={"approved_amount": "1.00"}, headers=auth["reporter"]
    )
    assert r.status_code == 403
    # 查勘员不能发起付款
    bid = partial_batch(client, auth, [1, 2])
    accept_batch(client, auth, bid)
    r = client.post(
        f"/batches/{bid}/pay", json={"gateway_outcome": "success"}, headers=auth["surveyor"]
    )
    assert r.status_code == 403
    # 未认证请求被拒绝
    assert client.get("/claims/1").status_code == 401


def test_reporter_can_add_new_loss_item(client, auth):
    r = client.post(
        "/claims/1/items",
        json={
            "title": "院门围墙倒塌",
            "category": "building",
            "claimed_amount": "6000.00",
            "file_name": "wall.zip",
            "file_note": "围墙损失照片",
        },
        headers=auth["reporter"],
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]
    r = client.post(
        f"/items/{item_id}/survey",
        json={"approved_amount": "5000.00"},
        headers=auth["surveyor"],
    )
    assert r.status_code == 200
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert any(i["id"] == item_id and i["approved_amount"] == "5000.00" for i in detail["items"])
