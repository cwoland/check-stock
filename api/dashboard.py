from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import select

from api import db
from api.models import Product, Receipt, RetiredWarehouse, Shipment, Stock, Transfer, Warehouse

router = APIRouter()


@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).with_name("dashboard.html"), media_type="text/html")


@router.get("/inventory")
def inventory():
    with db.SessionLocal() as session:
        # Read balances and movements at the same point in time.
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        def rows(model, *columns):
            return [
                dict(row)
                for row in session.execute(
                    select(*columns).order_by(*model.__table__.primary_key.columns)
                ).mappings()
            ]

        return {
            "products": rows(Product, Product.sku, Product.name),
            "warehouses": rows(Warehouse, Warehouse.id, Warehouse.name, Warehouse.archived_at),
            "retired": rows(RetiredWarehouse, RetiredWarehouse.id, RetiredWarehouse.name),
            "stock": rows(Stock, Stock.sku, Stock.warehouse_id, Stock.physical, Stock.reserved,
                          (Stock.physical - Stock.reserved).label("available")),
            "receipts": rows(Receipt, Receipt.sku, Receipt.warehouse_name, Receipt.quantity,
                             Receipt.created_at),
            "transfers": rows(Transfer, Transfer.id, Transfer.sku, Transfer.source_name,
                              Transfer.destination_name, Transfer.quantity, Transfer.sent_at,
                              Transfer.received_at),
            "shipments": rows(Shipment, Shipment.id, Shipment.sku, Shipment.warehouse_name,
                              Shipment.kind, Shipment.status, Shipment.quantity,
                              Shipment.created_at, Shipment.confirmed_at),
        }
