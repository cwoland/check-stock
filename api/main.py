from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert

from api.db import SessionLocal
from api.models import Product, Receipt, Stock, Warehouse
from api.transfers import router as transfers_router


app = FastAPI(title='CheckStock')
app.include_router(transfers_router)


class ReceiptRequest(BaseModel):
    sku: Annotated[str, Field(min_length=1)]
    warehouse_id: Annotated[int, Field(gt=0)]
    quantity: Annotated[int, Field(gt=0, le=2_147_483_647)]


class ReceiptResult(BaseModel):
    id: UUID


@app.put('/receipts/{receipt_id}', response_model=ReceiptResult)
def receive_stock(receipt_id: UUID, request: ReceiptRequest) -> ReceiptResult:
    with SessionLocal.begin() as session:
        existing = session.get(Receipt, receipt_id)

        if existing is None:
            warehouse = session.get(
                Warehouse, request.warehouse_id, with_for_update=True
            )
            if warehouse is None:
                raise HTTPException(404, 'ФФ не найден')

            existing = session.get(Receipt, receipt_id)

        if existing is None:
            if warehouse.archived_at is not None:
                raise HTTPException(409, 'ФФ в архиве')
            if session.get(Product, request.sku) is None:
                raise HTTPException(404, 'Артикул не найден')

            receipt_insert = (
                insert(Receipt)
                .values(
                    id=receipt_id,
                    sku=request.sku,
                    warehouse_id=request.warehouse_id,
                    warehouse_name=warehouse.name,
                    quantity=request.quantity,
                )
                .on_conflict_do_nothing(index_elements=[Receipt.id])
                .returning(Receipt.id)
            )
            if session.scalar(receipt_insert) is not None:
                stock_insert = insert(Stock).values(
                    sku=request.sku,
                    warehouse_id=request.warehouse_id,
                    physical=request.quantity,
                    reserved=0,
                )
                session.execute(
                    stock_insert.on_conflict_do_update(
                        index_elements=[Stock.sku, Stock.warehouse_id],
                        set_={'physical': Stock.physical + stock_insert.excluded.physical},
                    )
                )
                return ReceiptResult(id=receipt_id)

            existing = session.get(Receipt, receipt_id)

        if (existing.sku, existing.warehouse_id, existing.quantity) != (
            request.sku,
            request.warehouse_id,
            request.quantity,
        ):
            raise HTTPException(409, 'Этот UUID уже использован')

        return ReceiptResult(id=receipt_id)
