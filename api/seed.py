"""Load the CheckStock demo data with python -m api.seed."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from api.db import SessionLocal
from api.models import Product, Receipt, Stock, Warehouse

PRODUCTS = (
    ("SKU-101", "Органайзер", 10, 6),
    ("SKU-102", "Контейнер", 5, 0),
    ("SKU-103", "Корзина", 0, 4),
)
WAREHOUSES = ("Север", "Юг")
DEMO_RECEIPTS = {
    (sku, warehouse): (uuid5(NAMESPACE_URL, f"check-stock/demo/{sku}/{warehouse}"), quantity)
    for sku, _, *quantities in PRODUCTS
    for warehouse, quantity in zip(WAREHOUSES, quantities, strict=True)
    if quantity
}


def load_demo_data() -> bool:
    with SessionLocal.begin() as session:
        # Serialize concurrent demo loads until the transaction commits.
        session.execute(select(func.pg_advisory_xact_lock(61080123)))
        receipt_ids = [receipt_id for receipt_id, _ in DEMO_RECEIPTS.values()]
        existing = session.scalars(
            select(Receipt.id).where(Receipt.id.in_(receipt_ids))
        ).all()
        if len(existing) == len(receipt_ids):
            return False
        if existing:
            raise RuntimeError("В базе найден только фрагмент демонстрационных приходов")

        session.execute(
            insert(Product)
            .values([{"sku": sku, "name": name} for sku, name, *_ in PRODUCTS])
            .on_conflict_do_nothing(index_elements=[Product.sku])
        )
        warehouses = {name: Warehouse(name=name) for name in WAREHOUSES}
        session.add_all(warehouses.values())
        session.flush()

        for (sku, warehouse_name), (receipt_id, quantity) in DEMO_RECEIPTS.items():
            warehouse_id = warehouses[warehouse_name].id
            session.add_all([
                Receipt(
                    id=receipt_id,
                    sku=sku,
                    warehouse_id=warehouse_id,
                    warehouse_name=warehouse_name,
                    quantity=quantity,
                ),
                Stock(sku=sku, warehouse_id=warehouse_id, physical=quantity, reserved=0),
            ])
    return True


if __name__ == "__main__":
    loaded = load_demo_data()
    print("Демонстрационные данные загружены" if loaded else "Данные уже загружены")
