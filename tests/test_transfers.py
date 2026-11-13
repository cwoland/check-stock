from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from api.models import Stock, Transfer, Warehouse
from test_receipts import client, sessions


@pytest.fixture
def transfer_request(sessions):
    with sessions.begin() as session:
        destination = Warehouse(name="Запад")
        session.add(destination)
        session.flush()
        session.add_all([
            Stock(sku="SKU-101", warehouse_id=1, physical=10, reserved=3),
            Stock(sku="SKU-101", warehouse_id=destination.id, physical=6, reserved=0),
        ])
        return {
            "sku": "SKU-101",
            "source_id": 1,
            "destination_id": destination.id,
            "quantity": 5,
        }


def test_send_and_concurrent_receive_are_idempotent(client, sessions, transfer_request):
    transfer_id = uuid4()
    url = f"/transfers/{transfer_id}"

    response = client.put(url, json=transfer_request)
    assert response.status_code == 200
    sent = response.json()
    assert sent["received_at"] is None
    assert sent["source_name"] == "Север"
    assert sent["destination_name"] == "Запад"
    assert client.put(url, json=transfer_request).json() == sent
    assert client.put(url, json=transfer_request | {"quantity": 6}).status_code == 409
    assert client.get("/transfers").json() == [sent]

    with sessions() as session:
        source = session.get(Stock, ("SKU-101", 1))
        destination = session.get(Stock, ("SKU-101", transfer_request["destination_id"]))
        assert (source.physical, source.reserved, destination.physical) == (5, 3, 6)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.put(f"{url}/receive"), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    received = responses[0].json()
    assert received == responses[1].json()
    assert received["received_at"] is not None
    assert client.get("/transfers").json() == [received]

    with sessions() as session:
        destination = session.get(Stock, ("SKU-101", transfer_request["destination_id"]))
        assert (destination.physical, destination.reserved) == (11, 0)


def test_insufficient_at_source_rolls_back_transfer(client, sessions, transfer_request):
    transfer_id = uuid4()
    response = client.put(f"/transfers/{transfer_id}", json=transfer_request | {"quantity": 8})

    assert response.status_code == 409
    assert response.json()["detail"]["source_available"] == 7
    assert response.json()["detail"]["total_available"] == 13
    with sessions() as session:
        assert session.get(Transfer, transfer_id) is None
        assert session.get(Stock, ("SKU-101", 1)).physical == 10


def test_archived_warehouse_rules(client, sessions, transfer_request):
    blocked = client.put(f"/transfers/{uuid4()}", json=transfer_request | {"destination_id": 2})
    assert blocked.status_code == 409

    url = f"/transfers/{uuid4()}"
    assert client.put(url, json=transfer_request).status_code == 200


    with sessions.begin() as session:
        session.get(Warehouse, transfer_request["destination_id"]).archived_at = datetime.now(UTC)

    assert client.put(f"{url}/receive").status_code == 200
    evacuation = transfer_request | {
        "source_id": transfer_request["destination_id"],
        "destination_id": transfer_request["source_id"],
    }
    assert client.put(f"/transfers/{uuid4()}", json=evacuation).status_code == 200
