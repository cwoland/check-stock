from uuid import uuid4

from api.models import Stock
from test_receipts import client, sessions


def test_dashboard_inventory_tracks_reserve_and_transfer(client, sessions):
    with sessions.begin() as session:
        session.add(Stock(sku="SKU-101", warehouse_id=1, physical=10, reserved=0))

    page = client.get("/")
    assert page.status_code == 200
    assert "Остатки и движения" in page.text

    warehouse = client.post("/warehouses", json={"name": "Запад"}).json()
    shipment = f"/shipments/{uuid4()}"
    transfer = f"/transfers/{uuid4()}"
    assert client.put(shipment, json={
        "sku": "SKU-101", "warehouse_id": 1, "quantity": 3, "kind": "fbs",
    }).status_code == 200
    assert client.put(transfer, json={
        "sku": "SKU-101", "source_id": 1, "destination_id": warehouse["id"], "quantity": 4,
    }).status_code == 200

    snapshot = client.get("/inventory").json()
    assert snapshot["stock"] == [
        {"sku": "SKU-101", "warehouse_id": 1, "physical": 6, "reserved": 3, "available": 3},
    ]
    assert snapshot["transfers"][0]["received_at"] is None
    assert snapshot["shipments"][0]["status"] == "reserved"

    assert client.put(f"{transfer}/receive").status_code == 200
    assert client.put(f"{shipment}/send").status_code == 200
    snapshot = client.get("/inventory").json()
    assert [row["physical"] for row in snapshot["stock"]] == [3, 4]
    assert snapshot["transfers"][0]["received_at"] is not None
    assert snapshot["shipments"][0]["status"] == "sent"
