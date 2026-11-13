from uuid import uuid4

import pytest

from api.models import Shipment, Stock
from test_receipts import client, sessions


@pytest.mark.parametrize(
    ("kind", "action", "initial", "after_create", "final", "after_action"),
    [
        ("fbs", "send", "reserved", (10, 4), "sent", (6, 0)),
        ("fbs", "cancel", "reserved", (10, 4), "cancelled", (10, 0)),
        ("fbo", "receive", "sent", (6, 0), "received", (6, 0)),
    ],
)
def test_shipment_lifecycle(client, sessions, kind, action, initial, after_create, final, after_action):
    with sessions.begin() as session:
        session.add(Stock(sku="SKU-101", warehouse_id=1, physical=10, reserved=0))

    def counts():
        with sessions() as session:
            stock = session.get_one(Stock, ("SKU-101", 1))
            return stock.physical, stock.reserved

    url = f"/shipments/{uuid4()}"
    payload = {"sku": "SKU-101", "warehouse_id": 1, "kind": kind, "quantity": 4}
    for _ in range(2):
        response = client.put(url, json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == initial
        assert counts() == after_create
    for _ in range(2):
        response = client.put(f"{url}/{action}")
        assert response.status_code == 200
        assert response.json()["status"] == final
        assert counts() == after_action
    assert client.get("/shipments").json() == [response.json()]
    assert client.put(url, json=payload | {"quantity": 5}).status_code == 409


@pytest.mark.parametrize("kind", ["fbs", "fbo"])
def test_shortage_does_not_use_stock_from_other_warehouses(client, sessions, kind):
    with sessions.begin() as session:
        session.add_all([
            Stock(sku="SKU-101", warehouse_id=1, physical=3, reserved=0),
            Stock(sku="SKU-101", warehouse_id=2, physical=20, reserved=0),
        ])
    shipment_id = uuid4()
    response = client.put(
        f"/shipments/{shipment_id}",
        json={"sku": "SKU-101", "warehouse_id": 1, "kind": kind, "quantity": 4},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["source_available"] == 3
    with sessions() as session:
        assert session.get(Shipment, shipment_id) is None
        assert session.get_one(Stock, ("SKU-101", 1)).physical == 3
