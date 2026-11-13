from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from api import db
from api.models import Product, Shipment, Stock, Warehouse

router = APIRouter(prefix="/shipments", tags=["shipments"])


class ShipmentRequest(BaseModel):
    kind: Literal["fbs", "fbo"]
    sku: Annotated[str, Field(min_length=1)]
    warehouse_id: Annotated[int, Field(gt=0)]
    quantity: Annotated[int, Field(gt=0, le=2_147_483_647)]


class ShipmentResult(ShipmentRequest):
    id: UUID
    warehouse_name: str
    status: Literal["reserved", "sent", "cancelled", "received"]
    created_at: datetime
    confirmed_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ShipmentResult])
def list_shipments() -> list[ShipmentResult]:
    with db.SessionLocal() as session:
        return [
            ShipmentResult.model_validate(row)
            for row in session.scalars(select(Shipment).order_by(Shipment.created_at, Shipment.id))
        ]


@router.put("/{shipment_id}", response_model=ShipmentResult)
def create_shipment(shipment_id: UUID, request: ShipmentRequest) -> ShipmentResult:
    values = request.model_dump()
    with db.SessionLocal.begin() as session:
        existing = session.get(Shipment, shipment_id)
        if existing is None:
            warehouse = session.get(Warehouse, request.warehouse_id, with_for_update=True)
            existing = session.get(Shipment, shipment_id)
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items()):
                raise HTTPException(409, "Этот UUID уже использован для другой отправки")
            return ShipmentResult.model_validate(existing)

        if warehouse is None or session.get(Product, request.sku) is None:
            raise HTTPException(404, "ФФ или артикул не найден")
        if warehouse.archived_at is not None:
            raise HTTPException(409, "ФФ в архиве")

        shipment = session.scalar(
            insert(Shipment)
            .values(
                id=shipment_id,
                **values,
                warehouse_name=warehouse.name,
                status="reserved" if request.kind == "fbs" else "sent",
            )
            .on_conflict_do_nothing(index_elements=[Shipment.id])
            .returning(Shipment)
        )
        if shipment is None:
            raise HTTPException(409, "Этот UUID уже использован для другой отправки")

        stock = session.get(Stock, (request.sku, request.warehouse_id), with_for_update=True)
        available = stock.physical - stock.reserved if stock is not None else 0
        if stock is None or available < request.quantity:
            raise HTTPException(409, {
                "message": "На выбранном ФФ недостаточно доступного товара",
                "source_available": available,
            })
        if request.kind == "fbs":
            stock.reserved += request.quantity
        else:
            stock.physical -= request.quantity
        return ShipmentResult.model_validate(shipment)


TRANSITIONS = {
    ("fbs", "send"): ("reserved", "sent"),
    ("fbs", "cancel"): ("reserved", "cancelled"),
    ("fbo", "receive"): ("sent", "received"),
}


@router.put("/{shipment_id}/{action}", response_model=ShipmentResult)
def update_shipment(
    shipment_id: UUID, action: Literal["send", "cancel", "receive"]
) -> ShipmentResult:
    with db.SessionLocal.begin() as session:
        shipment = session.get(Shipment, shipment_id, with_for_update=True)
        if shipment is None:
            raise HTTPException(404, "Отправка не найдена")
        transition = TRANSITIONS.get((shipment.kind, action))
        if transition is None:
            raise HTTPException(409, "Действие недоступно для этого типа отправки")
        previous, target = transition
        if shipment.status == target:
            return ShipmentResult.model_validate(shipment)
        if shipment.status != previous:
            raise HTTPException(409, "Действие недоступно в текущем статусе")

        if shipment.kind == "fbs":
            stock = session.get_one(
                Stock, (shipment.sku, shipment.warehouse_id), with_for_update=True
            )
            stock.reserved -= shipment.quantity
            if action == "send":
                stock.physical -= shipment.quantity
        shipment.status = target
        shipment.confirmed_at = session.scalar(select(func.clock_timestamp()))
        return ShipmentResult.model_validate(shipment)
