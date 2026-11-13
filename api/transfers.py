from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from api import db
from api.models import Product, Stock, Transfer, Warehouse

router = APIRouter(prefix="/transfers", tags=["transfers"])


class TransferRequest(BaseModel):
    sku: Annotated[str, Field(min_length=1)]
    source_id: Annotated[int, Field(gt=0)]
    destination_id: Annotated[int, Field(gt=0)]
    quantity: Annotated[int, Field(gt=0, le=2_147_483_647)]


class TransferResult(TransferRequest):
    id: UUID
    source_name: str
    destination_name: str
    sent_at: datetime
    received_at: datetime | None


def result(transfer: Transfer) -> TransferResult:
    return TransferResult.model_validate(transfer, from_attributes=True)


def check_retry(transfer: Transfer, request: TransferRequest) -> TransferResult:
    if (transfer.sku, transfer.source_id, transfer.destination_id, transfer.quantity) != (
        request.sku, request.source_id, request.destination_id, request.quantity
    ):
        raise HTTPException(409, "Этот UUID уже использован для другого перемещения")
    return result(transfer)


@router.get("", response_model=list[TransferResult])
def list_transfers() -> list[TransferResult]:
    with db.SessionLocal() as session:
        transfers = session.scalars(select(Transfer).order_by(Transfer.sent_at.desc(), Transfer.id))
        return [result(transfer) for transfer in transfers]


@router.put("/{transfer_id}", response_model=TransferResult)
def send_transfer(transfer_id: UUID, request: TransferRequest) -> TransferResult:
    if request.source_id == request.destination_id:
        raise HTTPException(422, "Укажите разные ФФ")

    with db.SessionLocal.begin() as session:
        existing = session.get(Transfer, transfer_id)
        if existing is not None:
            return check_retry(existing, request)

        # Lock both warehouses in a consistent order for opposite-direction sends.
        warehouses = {
            warehouse.id: warehouse
            for warehouse in session.scalars(
                select(Warehouse)
                .where(Warehouse.id.in_((request.source_id, request.destination_id)))
                .order_by(Warehouse.id)
                .with_for_update()
            )
        }
        existing = session.get(Transfer, transfer_id)
        if existing is not None:
            return check_retry(existing, request)

        if len(warehouses) != 2:
            raise HTTPException(404, "ФФ не найден")
        source = warehouses[request.source_id]
        destination = warehouses[request.destination_id]
        if destination.archived_at is not None:
            raise HTTPException(409, "ФФ назначения в архиве")
        if session.get(Product, request.sku) is None:
            raise HTTPException(404, "Артикул не найден")

        transfer = session.scalar(
            insert(Transfer)
            .values(
                id=transfer_id,
                **request.model_dump(),
                source_name=source.name,
                destination_name=destination.name,
            )
            .on_conflict_do_nothing(index_elements=[Transfer.id])
            .returning(Transfer)
        )
        if transfer is None:
            return check_retry(session.get_one(Transfer, transfer_id), request)

        stock = session.get(Stock, (request.sku, source.id), with_for_update=True)
        available = stock.physical - stock.reserved if stock is not None else 0
        if stock is None or available < request.quantity:
            total_available = session.scalar(
                select(func.coalesce(func.sum(Stock.physical - Stock.reserved), 0))
                .where(Stock.sku == request.sku)
            )
            raise HTTPException(409, {
                "message": "На выбранном ФФ недостаточно доступного товара",
                "source_available": available,
                "total_available": total_available,
            })

        stock.physical -= request.quantity
        return result(transfer)


@router.put("/{transfer_id}/receive", response_model=TransferResult)
def receive_transfer(transfer_id: UUID) -> TransferResult:
    with db.SessionLocal.begin() as session:
        transfer = session.get(Transfer, transfer_id, with_for_update=True)
        if transfer is None:
            raise HTTPException(404, "Перемещение не найдено")
        if transfer.received_at is not None:
            return result(transfer)

        session.get_one(Warehouse, transfer.destination_id, with_for_update=True)
        stock_insert = insert(Stock).values(
            sku=transfer.sku,
            warehouse_id=transfer.destination_id,
            physical=transfer.quantity,
            reserved=0,
        )
        session.execute(
            stock_insert.on_conflict_do_update(
                index_elements=[Stock.sku, Stock.warehouse_id],
                set_={"physical": Stock.physical + stock_insert.excluded.physical},
            )
        )
        transfer.received_at = session.scalar(select(func.clock_timestamp()))
        return result(transfer)
