import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import reset_and_seed
from app.services.gateway import gateway


@pytest.fixture()
def client():
    reset_and_seed()
    gateway.reset()
    with TestClient(app) as c:
        yield c


def login(client: TestClient, username: str) -> dict:
    resp = client.post("/auth/login", json={"username": username, "password": "test1234"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['token']}"}


@pytest.fixture()
def auth(client):
    return {
        "reporter": login(client, "reporter"),
        "surveyor": login(client, "surveyor"),
        "adjuster": login(client, "adjuster"),
        "zhao": login(client, "officer_zhao"),
        "qian": login(client, "officer_qian"),
    }
