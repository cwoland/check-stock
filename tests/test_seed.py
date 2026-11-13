from sqlalchemy import select

from api import seed
from api.models import Product, Receipt, Stock, Warehouse
from test_receipts import sessions


def test_demo_data_matches_assignment_and_loads_once(sessions, monkeypatch):
    monkeypatch.setattr(seed, "SessionLocal", sessions)

    assert seed.load_demo_data() is True
    assert seed.load_demo_data() is False

    with sessions() as session:
        products = session.execute(select(Product.sku, Product.name)).all()
        demo_receipts = session.execute(
            select(Receipt.sku, Receipt.warehouse_name, Receipt.quantity)
        ).all()
        demo_stock = session.execute(
            select(Stock.sku, Warehouse.name, Stock.physical, Stock.reserved)
            .join(Warehouse, Stock.warehouse_id == Warehouse.id)
            .join(Receipt, (Receipt.warehouse_id == Stock.warehouse_id) & (Receipt.sku == Stock.sku))
        ).all()

    assert sorted(products) == [
        ("SKU-101", "Органайзер"),
        ("SKU-102", "Контейнер"),
        ("SKU-103", "Корзина"),
    ]
    expected = [
        ("SKU-101", "Север", 10),
        ("SKU-101", "Юг", 6),
        ("SKU-102", "Север", 5),
        ("SKU-103", "Юг", 4),
    ]
    assert sorted(demo_receipts) == expected
    assert sorted(demo_stock) == [(*row, 0) for row in expected]
