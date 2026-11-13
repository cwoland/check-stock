from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from api.models import Receipt, RetiredWarehouse, Stock, Warehouse
from api.warehouses import purge_archived_warehouses
from test_receipts import client, sessions


def set_archive_age(sessions, warehouse_id, days):
    with sessions.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        session.get_one(Warehouse, warehouse_id).archived_at = now - timedelta(days=days)


def test_warehouse_crud_and_archive_is_idempotent(client):
    response = client.post("/warehouses", json={"name": " Восток "})
    assert response.status_code == 201
    warehouse = response.json()
    assert warehouse["name"] == "Восток"
    assert warehouse["archived_at"] is None

    url = f"/warehouses/{warehouse['id']}"
    assert client.patch(url, json={"name": "Восток-2"}).json()["name"] == "Восток-2"
    assert client.delete(url).status_code == 204
    archived = next(row for row in client.get("/warehouses").json() if row["id"] == warehouse["id"])
    assert archived["archived_at"] is not None
    assert client.delete(url).status_code == 204
    assert archived in client.get("/warehouses").json()
    assert client.patch(url, json={"name": "Смена"}).status_code == 409
    assert purge_archived_warehouses() == 0


def test_purge_keeps_stock_history_and_receipt_retries(client, sessions):
    url = f"/receipts/{uuid4()}"
    payload = {"sku": "SKU-101", "warehouse_id": 1, "quantity": 10}
    assert client.put(url, json=payload).status_code == 200
    assert client.patch("/warehouses/1", json={"name": "Север-2"}).status_code == 200
    set_archive_age(sessions, 1, 31)
    set_archive_age(sessions, 2, 29)

    assert purge_archived_warehouses() == 1
    assert purge_archived_warehouses() == 0
    assert {row["id"] for row in client.get("/warehouses").json()} == {2}
    assert client.delete("/warehouses/1").status_code == 204
    assert client.put(url, json=payload).status_code == 200
    assert client.put(f"/receipts/{uuid4()}", json=payload).status_code == 404

    with sessions() as session:
        assert session.get_one(RetiredWarehouse, 1).name == "Север-2"
        assert session.get_one(Stock, ("SKU-101", 1)).physical == 10
        receipt = session.scalars(select(Receipt)).one()
        assert (receipt.warehouse_id, receipt.warehouse_name) == (1, "Север")


def test_receive_transfer_after_destination_is_removed(client, sessions):
    with sessions.begin() as session:
        destination = Warehouse(name="Запад")
        session.add(destination)
        session.add(Stock(sku="SKU-101", warehouse_id=1, physical=10, reserved=0))
        session.flush()
        destination_id = destination.id

    url = f"/transfers/{uuid4()}"
    assert client.put(url, json={
        "sku": "SKU-101", "source_id": 1, "destination_id": destination_id, "quantity": 4,
    }).status_code == 200

    set_archive_age(sessions, destination_id, 31)
    assert purge_archived_warehouses() == 1
    received = client.put(f"{url}/receive")
    assert received.status_code == 200
    assert received.json()["received_at"] is not None
    assert client.put(f"{url}/receive").json() == received.json()

    with sessions() as session:
        assert session.get_one(Stock, ("SKU-101", destination_id)).physical == 4


def test_startup_purges_expired_warehouses(sessions):
    from fastapi.testclient import TestClient

    from api.main import app

    set_archive_age(sessions, 1, 31)
    with TestClient(app) as client:
        assert {row["id"] for row in client.get("/warehouses").json()} == {2}
