from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from api import db, main
from api.models import Product, Receipt, Stock, Warehouse


@pytest.fixture
def sessions(monkeypatch):
    engine = create_engine("postgresql+psycopg://localhost:5432/check_stock_test")
    test_sessions = sessionmaker(engine)
    monkeypatch.setattr(main, "SessionLocal", test_sessions)
    monkeypatch.setattr(db, "SessionLocal", test_sessions)

    def clear_tables():
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE transfers, receipts, stock, products, warehouses RESTART IDENTITY"))

    try:
        clear_tables()
        with test_sessions.begin() as session:
            session.add_all([
                Product(sku="SKU-101", name="Органайзер"),
                Warehouse(name="Север"),
                Warehouse(name="Юг", archived_at=datetime.now(UTC)),
            ])
        yield test_sessions
    finally:
        clear_tables()
        engine.dispose()


@pytest.fixture
def client(sessions):
    with TestClient(main.app) as test_client:
        yield test_client


def test_receipt_updates_stock_and_records_history(client, sessions):
    receipt_id = uuid4()
    response = client.put(
        f"/receipts/{receipt_id}",
        json={"sku": "SKU-101", "warehouse_id": 1, "quantity": 10},
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(receipt_id)}

    with sessions() as session:
        stock = session.get(Stock, ("SKU-101", 1))
        receipt = session.get(Receipt, receipt_id)
        assert (stock.physical, stock.reserved) == (10, 0)
        assert (receipt.sku, receipt.warehouse_name, receipt.quantity) == (
            "SKU-101", "Север", 10
        )


def test_concurrent_retries_credit_stock_once(client, sessions):
    url = f"/receipts/{uuid4()}"
    payload = {"sku": "SKU-101", "warehouse_id": 1, "quantity": 10}

    def send_receipt():
        return client.put(url, json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        requests = [executor.submit(send_receipt) for _ in range(2)]
        responses = [request.result() for request in requests]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert client.put(url, json={**payload, "quantity": 11}).status_code == 409

    with sessions() as session:
        assert session.get(Stock, ("SKU-101", 1)).physical == 10
        assert session.scalar(select(func.count()).select_from(Receipt)) == 1


@pytest.mark.parametrize(
    ("payload_override", "expected_status"),
    [
        ({"quantity": 0}, 422),
        ({"warehouse_id": 2}, 409),
        ({"warehouse_id": 99}, 404),
        ({"sku": "UNKNOWN"}, 404),
    ],
)
def test_rejected_receipt_leaves_no_stock_or_history(
    client, sessions, payload_override, expected_status
):
    payload = {"sku": "SKU-101", "warehouse_id": 1, "quantity": 10}
    response = client.put(f"/receipts/{uuid4()}", json=payload | payload_override)

    assert response.status_code == expected_status
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == 0
        assert session.scalar(select(func.count()).select_from(Stock)) == 0