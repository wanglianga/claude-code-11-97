"""支付模拟器与并发/幂等纪律。"""
import threading

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.enums import PaymentStatus
from app.main import app
from app.models import Payment
from app.services.gateway import gateway


def _accepted_batch(client, auth):
    r = client.post(
        "/claims/1/batches",
        json={"kind": "partial", "item_ids": [1, 2]},
        headers=auth["adjuster"],
    )
    bid = r.json()["id"]
    client.post(f"/batches/{bid}/accept", json={"accepted": True}, headers=auth["reporter"])
    return bid


def test_success_receipt_lost_then_query_succeeds(client, auth):
    """成功后响应丢失：付款保持结果未知并占额度，查询后成功，不重新生成付款。"""
    bid = _accepted_batch(client, auth)
    r = client.post(
        f"/batches/{bid}/pay",
        json={"gateway_outcome": "success_receipt_lost"},
        headers=auth["zhao"],
    )
    assert r.status_code == 200, r.text
    payment = r.json()
    pid = payment["id"]
    assert payment["status"] == "submitted_unknown"
    assert payment["gateway_ref"]

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    # 结果未知仍占用事故额度
    assert detail["money"]["reserved_total"] == "25000.00"
    assert detail["progress"]["stage"] == "payment_unknown"
    assert any("查询回执" in a for a in detail["progress"]["actions"])

    # 在途期间禁止再发起一笔
    r = client.post(
        f"/batches/{bid}/pay",
        json={"gateway_outcome": "success"},
        headers=auth["qian"],
    )
    assert r.status_code == 409
    assert "禁止重复发起" in r.json()["detail"]

    # 凭原交易号查询，取得成功回执（同一笔付款）
    r = client.post(f"/payments/{pid}/query", headers=auth["zhao"])
    assert r.status_code == 200, r.text
    assert r.json()["id"] == pid
    assert r.json()["status"] == "succeeded"
    assert r.json()["poll_count"] == 1

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["money"]["succeeded_total"] == "25000.00"
    assert detail["money"]["reserved_total"] == "0.00"
    # 自始至终只有一笔付款
    assert len(detail["payments"]) == 1
    event_types = [e["event_type"] for e in detail["payments"][0]["events"]]
    assert "receipt_lost" in event_types and "query_succeeded" in event_types


def test_late_success_needs_two_polls(client, auth):
    """首次查询仍处理中，稍后再次查询成功。"""
    bid = _accepted_batch(client, auth)
    r = client.post(
        f"/batches/{bid}/pay",
        json={"gateway_outcome": "late_success"},
        headers=auth["zhao"],
    )
    assert r.json()["status"] == "timed_out"
    pid = r.json()["id"]

    r = client.post(f"/payments/{pid}/query", headers=auth["zhao"])
    assert r.json()["status"] == "submitted_unknown"  # 第一次查询：仍处理中
    assert r.json()["poll_count"] == 1

    # 仍占额度、仍禁止重复发起
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["money"]["reserved_total"] == "25000.00"

    r = client.post(f"/payments/{pid}/query", headers=auth["zhao"])
    assert r.json()["status"] == "succeeded"  # 稍后查询成功
    assert r.json()["poll_count"] == 2
    assert client.get("/claims/1", headers=auth["reporter"]).json()["money"][
        "succeeded_total"
    ] == "25000.00"


def test_explicit_decline_frees_capacity_and_allows_repay(client, auth):
    """明确拒绝不占额度，可在同批次重新发起付款。"""
    bid = _accepted_batch(client, auth)
    r = client.post(
        f"/batches/{bid}/pay",
        json={"gateway_outcome": "decline"},
        headers=auth["zhao"],
    )
    assert r.json()["status"] == "declined"
    declined_id = r.json()["id"]

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["money"]["reserved_total"] == "0.00"
    assert detail["progress"]["stage"] == "awaiting_payment"

    # 重新发起（新的一笔，原拒绝记录保留审计）
    r = client.post(
        f"/batches/{bid}/pay",
        json={"gateway_outcome": "success"},
        headers=auth["qian"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded"
    assert r.json()["id"] != declined_id

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    statuses = sorted(p["status"] for p in detail["payments"])
    assert statuses == ["declined", "succeeded"]
    assert detail["money"]["succeeded_total"] == "25000.00"


def test_two_officers_concurrent_payment_only_one_succeeds(client, auth):
    """两名复核员同时付款：行锁 + 在途检查保证只有一笔出款。"""
    bid = _accepted_batch(client, auth)
    results: list[int] = []
    errors: list[int] = []
    barrier = threading.Barrier(2)
    zhao_token = auth["zhao"]["Authorization"]
    qian_token = auth["qian"]["Authorization"]

    def pay_as(token: str):
        # 每个线程使用独立的 TestClient（共享同一 app 与数据库）
        local_client = TestClient(app)
        barrier.wait()
        r = local_client.post(
            f"/batches/{bid}/pay",
            json={"gateway_outcome": "success"},
            headers={"Authorization": token},
        )
        if r.status_code == 200:
            results.append(r.json()["id"])
        else:
            errors.append(r.status_code)

    t1 = threading.Thread(target=pay_as, args=(zhao_token,))
    t2 = threading.Thread(target=pay_as, args=(qian_token,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results) == 1, f"应只有一笔付款成功，实际成功 {len(results)}，失败 {errors}"
    assert errors == [409]

    db = SessionLocal()
    try:
        payments = db.query(Payment).filter(Payment.batch_id == bid).all()
        assert len(payments) == 1
        assert payments[0].status == PaymentStatus.SUCCEEDED
        assert payments[0].amount.__str__() == "25000.00"
    finally:
        db.close()

    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["money"]["succeeded_total"] == "25000.00"
    assert detail["money"]["remaining_liability"] == "0.00"


def test_capacity_reserved_blocks_overpayment_across_batches(client, auth):
    """在途占用期间，新批次付款被阻塞，避免超出事故责任。"""
    bid1 = _accepted_batch(client, auth)
    r = client.post(
        f"/batches/{bid1}/pay",
        json={"gateway_outcome": "success_receipt_lost"},
        headers=auth["zhao"],
    )
    assert r.json()["status"] == "submitted_unknown"

    # 第三项认可后建立补差批次并接受
    r = client.post(
        "/items/3/material-request",
        json={"request_note": "补充吊顶凭证"},
        headers=auth["adjuster"],
    )
    mid = r.json()["id"]
    client.post(
        f"/materials/{mid}/submit",
        json={"file_name": "p.pdf", "file_note": "凭证"},
        headers=auth["reporter"],
    )
    client.post("/items/3/recognize", json={"approved_amount": "8000.00"}, headers=auth["surveyor"])
    client.post(
        f"/materials/{mid}/review", json={"accept": True, "review_note": "ok"}, headers=auth["adjuster"]
    )
    r = client.post(
        "/claims/1/batches",
        json={"kind": "partial", "item_ids": [3]},
        headers=auth["adjuster"],
    )
    bid2 = r.json()["id"]
    client.post(f"/batches/{bid2}/accept", json={"accepted": True}, headers=auth["reporter"])

    # 第一笔仍在途（占 25000），第二笔可付额仅为 8000
    r = client.post(
        f"/batches/{bid2}/pay",
        json={"gateway_outcome": "success"},
        headers=auth["qian"],
    )
    assert r.status_code == 200
    assert r.json()["amount"] == "8000.00"

    # 两笔都成功后累计 33000，未超上限且免赔只扣一次
    first_pid = client.get("/claims/1", headers=auth["reporter"]).json()["payments"][0]["id"]
    client.post(f"/payments/{first_pid}/query", headers=auth["zhao"])
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    assert detail["money"]["succeeded_total"] == "33000.00"
    assert detail["money"]["remaining_liability"] == "0.00"


def test_limit_cap_is_enforced(client, auth):
    """赔偿上限约束：构造认可总额超过上限的情形，累计应赔被截断为 40000。"""
    # 新增一个认可 20000 的项目：认可总额变为 50000
    r = client.post(
        "/claims/1/items",
        json={
            "title": "附属厨房重建",
            "category": "building",
            "claimed_amount": "22000.00",
            "file_name": "kitchen.zip",
            "file_note": "重建报价",
        },
        headers=auth["reporter"],
    )
    new_id = r.json()["id"]
    client.post(
        f"/items/{new_id}/survey",
        json={"approved_amount": "20000.00"},
        headers=auth["surveyor"],
    )
    detail = client.get("/claims/1", headers=auth["reporter"]).json()
    # 认可总额 50000；应赔 = min(50000-5000, 40000) = 40000
    assert detail["money"]["approved_total"] == "50000.00"
    assert detail["money"]["cumulative_indemnity"] == "40000.00"
    assert detail["money"]["remaining_liability"] == "40000.00"
