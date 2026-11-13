from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import db
from api.models import RetiredWarehouse, Warehouse

router = APIRouter(prefix="/warehouses", tags=["warehouses"])
RETENTION = timedelta(days=30)


class WarehouseRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WarehouseResult(BaseModel):
    id: int
    name: str
    archived_at: datetime | None

    model_config = {"from_attributes": True}


def lock_warehouse(session: Session, warehouse_id: int) -> Warehouse:
    warehouse = session.get(Warehouse, warehouse_id, with_for_update=True)
    if warehouse is None:
        raise HTTPException(404, "ФФ не найден")
    return warehouse


@router.get("", response_model=list[WarehouseResult])
def list_warehouses() -> list[WarehouseResult]:
    with db.SessionLocal() as session:
        warehouses = session.scalars(select(Warehouse).order_by(Warehouse.id))
        return [WarehouseResult.model_validate(warehouse) for warehouse in warehouses]


@router.post("", response_model=WarehouseResult, status_code=201)
def create_warehouse(request: WarehouseRequest) -> WarehouseResult:
    with db.SessionLocal.begin() as session:
        warehouse = Warehouse(name=request.name)
        session.add(warehouse)
        session.flush()
        return WarehouseResult.model_validate(warehouse)


@router.patch("/{warehouse_id}", response_model=WarehouseResult)
def rename_warehouse(warehouse_id: int, request: WarehouseRequest) -> WarehouseResult:
    with db.SessionLocal.begin() as session:
        warehouse = lock_warehouse(session, warehouse_id)
        if warehouse.archived_at is not None:
            raise HTTPException(409, "ФФ в архиве")
        warehouse.name = request.name
        return WarehouseResult.model_validate(warehouse)


@router.delete("/{warehouse_id}", status_code=204)
def archive_warehouse(warehouse_id: int) -> None:
    with db.SessionLocal.begin() as session:
        warehouse = session.get(Warehouse, warehouse_id, with_for_update=True)
        if warehouse is None:
            if session.get(RetiredWarehouse, warehouse_id) is not None:
                return
            raise HTTPException(404, "ФФ не найден")

        if warehouse.archived_at is None:
            warehouse.archived_at = session.scalar(select(func.clock_timestamp()))


def purge_archived_warehouses() -> int:
    with db.SessionLocal.begin() as session:
        now = session.scalar(select(func.clock_timestamp()))
        expired = session.scalars(
            select(Warehouse)
            .where(Warehouse.archived_at <= now - RETENTION)
            .order_by(Warehouse.id)
            .with_for_update()
        ).all()

        for warehouse in expired:
            session.add(
                RetiredWarehouse(
                    id=warehouse.id,
                    name=warehouse.name,
                    deleted_at=now,
                )
            )
            session.delete(warehouse)

        return len(expired)