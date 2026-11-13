from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func, Identity
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base


class Product(Base):
    __tablename__ = 'products'

    sku: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]


class Warehouse(Base):
    __tablename__ = 'warehouses'

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str]
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Stock(Base):
    __tablename__ = 'stock'
    __table_args__ = (
        CheckConstraint('reserved >= 0', name='ck_stock_reserved_nonnegative'),
        CheckConstraint('physical >= reserved', name='ck_stock_physical_covers_reserve'),
    )

    sku: Mapped[str] = mapped_column(ForeignKey('products.sku'), primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(primary_key=True)
    physical: Mapped[int]
    reserved: Mapped[int]


class Receipt(Base):
    __tablename__ = 'receipts'
    __table_args__ = (
        CheckConstraint('quantity > 0', name='ck_receipts_quantity_positive'),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey('products.sku'))
    warehouse_id: Mapped[int]
    warehouse_name: Mapped[str]
    quantity: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_transfers_quantity_positive"),
        CheckConstraint("source_id <> destination_id", name="ck_transfers_distinct_warehouses"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    source_id: Mapped[int]
    destination_id: Mapped[int]
    source_name: Mapped[str]
    destination_name: Mapped[str]
    quantity: Mapped[int]
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_shipments_quantity_positive"),
        CheckConstraint(
            "(kind = 'fbs' AND status IN ('reserved', 'sent', 'cancelled')) OR "
            "(kind = 'fbo' AND status IN ('sent', 'received'))",
            name="ck_shipments_kind_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(ForeignKey("products.sku"))
    warehouse_id: Mapped[int]
    warehouse_name: Mapped[str]
    kind: Mapped[str]
    status: Mapped[str]
    quantity: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetiredWarehouse(Base):
    __tablename__ = 'retired_warehouses'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str]
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
