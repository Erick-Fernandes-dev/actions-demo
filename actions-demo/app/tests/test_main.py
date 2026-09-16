from fastapi.testclient import TestClient

from app.main import _db, app

client = TestClient(app)


def setup_function():
    _db.clear()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_get_item():
    r = client.post("/items", json={"name": "teclado", "price": 199.9})
    assert r.status_code == 201
    item_id = r.json()["id"]

    r = client.get(f"/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "teclado"


def test_negative_price_rejected():
    r = client.post("/items", json={"name": "x", "price": -1})
    assert r.status_code == 422


def test_item_not_found():
    assert client.get("/items/999").status_code == 404
