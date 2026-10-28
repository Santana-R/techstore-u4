"""Adaptador HTTP. El dominio protege las reglas y las transiciones."""
from threading import RLock
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from app.domain import (DomainException, InvalidOrderTransition, OrderStatus,
                        Money, OrderItem)
from app.specifications import quote_discount
from cargar_csv import load_fixture, rows
from decimal import Decimal


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ShipBody(StrictBody):
    tracking_number: str = Field(examples=["GUIA-U4-001"])


class CancelBody(StrictBody):
    reason: str = Field(examples=["Solicitud del cliente"])


class ItemBody(StrictBody):
    sku: str = Field(examples=["SKU003"])
    quantity: int = Field(gt=0, examples=[2])


class ItemView(BaseModel):
    sku: str
    quantity: int
    unit_price: str
    subtotal: str


class EventView(BaseModel):
    name: str
    order_id: str
    customer_id: str
    total: str
    occurred_at: str
    tracking_number: str | None
    reason: str | None


class OrderView(BaseModel):
    id: str
    customer_id: str
    status: OrderStatus
    units: int
    currency: Literal["MXN"]
    total: str
    discount_percent: str
    discount: str
    payable: str
    items: list[ItemView]
    events: list[EventView]


def to_view(order):
    quote = quote_discount(order)
    return {
        "id": order.id, "customer_id": order.customer.id,
        "status": order.status.value, "units": order.units, "currency": "MXN",
        "total": f"{order.total.amount:.2f}",
        "discount_percent": f"{quote.rate * 100:.0f}",
        "discount": f"{quote.discount.amount:.2f}", "payable": f"{quote.payable.amount:.2f}",
        "items": [{"sku": x.sku, "quantity": x.quantity,
                   "unit_price": f"{x.unit_price.amount:.2f}",
                   "subtotal": f"{x.subtotal.amount:.2f}"} for x in order.items],
        "events": [{"name": e.name, "order_id": e.order_id,
                    "customer_id": e.customer_id, "total": f"{e.total.amount:.2f}",
                    "occurred_at": e.occurred_at.isoformat(),
                    "tracking_number": e.tracking_number, "reason": e.reason}
                   for e in order.events],
    }


def create_app():
    api = FastAPI(title="TechStore U4", version="1.0.0",
                  description="Laboratorio CLNEG · Pedidos en memoria · FIME UANL")
    api.state.orders = load_fixture()
    api.state.lock = RLock()
    prices = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}

    @api.exception_handler(DomainException)
    async def domain_error(request: Request, exc: DomainException):
        status = 409 if isinstance(exc, InvalidOrderTransition) else 422
        return JSONResponse(status_code=status,
                            content={"detail": str(exc), "error": type(exc).__name__})

    def order_for(order_id):
        order = api.state.orders.get(order_id)
        if order is None:
            raise HTTPException(404, "Pedido inexistente")
        return order

    errors = {404: {"description": "Pedido inexistente"},
              409: {"description": "Transición no permitida"},
              422: {"description": "Datos o regla de negocio inválidos"}}

    @api.get("/orders/{order_id}", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def get_order(order_id: str):
        with api.state.lock:
            return to_view(order_for(order_id))

    @api.post("/orders/{order_id}/confirm", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def confirm_order(order_id: str):
        with api.state.lock:
            order = order_for(order_id)
            order.confirm()
            return to_view(order)

    @api.post("/orders/{order_id}/ship", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def ship_order(order_id: str, body: ShipBody):
        with api.state.lock:
            order = order_for(order_id)
            order.ship(body.tracking_number)
            return to_view(order)

    @api.post("/orders/{order_id}/cancel", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def cancel_order(order_id: str, body: CancelBody):
        with api.state.lock:
            order = order_for(order_id)
            order.cancel(body.reason)
            return to_view(order)

    @api.post("/orders/{order_id}/deliver", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def deliver_order(order_id: str):
        with api.state.lock:
            order = order_for(order_id)
            order.deliver()
            return to_view(order)

    @api.post("/orders/{order_id}/return", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def return_order(order_id: str):
        with api.state.lock:
            order = order_for(order_id)
            order.return_order()
            return to_view(order)

    @api.post("/orders/{order_id}/items", response_model=OrderView, tags=["Pedidos"], responses=errors)
    def add_item(order_id: str, body: ItemBody):
        with api.state.lock:
            order = order_for(order_id)
            if body.sku not in prices:
                raise HTTPException(404, "SKU inexistente")
            order.add_item(OrderItem(body.sku, body.quantity, Money(prices[body.sku])))
            return to_view(order)

    return api


app = create_app()
