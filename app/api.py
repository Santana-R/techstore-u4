"""Adaptador HTTP con respuestas legibles para el cliente en Swagger."""
from decimal import Decimal
from threading import RLock

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain import (DomainException, InvalidOrderTransition, Money,
                        OrderItem, OrderItemLimitExceeded, OrderStatus)
from app.specifications import quote_discount
from cargar_csv import load_fixture, rows


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ShipBody(StrictBody):
    tracking_number: str = Field(
        description="Número de guía del envío. No debe estar vacío.",
        examples=["GUIA-U4-001"],
    )


class CancelBody(StrictBody):
    reason: str = Field(
        description="Motivo de la cancelación. No debe estar vacío.",
        examples=["Solicitud del cliente"],
    )


class ItemBody(StrictBody):
    sku: str = Field(description="Código del producto en el catálogo.", examples=["SKU003"])
    quantity: int = Field(gt=0, description="Cantidad entera mayor que cero.", examples=[2])


STATES = {
    OrderStatus.DRAFT: "en preparación",
    OrderStatus.CONFIRMED: "confirmada",
    OrderStatus.SHIPPED: "enviada",
    OrderStatus.DELIVERED: "entregada",
    OrderStatus.CANCELLED: "cancelada",
    OrderStatus.RETURNED: "devuelta",
}

TRANSITION_HELP = {
    "confirm": "Solo se puede confirmar una orden que esté en preparación.",
    "ship": "Para enviar una orden, primero debe estar confirmada.",
    "cancel": "Solo se puede cancelar una orden confirmada que aún no se haya enviado.",
    "deliver": "Para registrar la entrega, la orden debe estar enviada.",
    "return": "Solo se puede devolver una orden que esté enviada.",
    "items": "Solo se pueden agregar productos mientras la orden esté en preparación.",
}

DATA_MESSAGES = {
    "El pedido no contiene artículos":
        "No se puede confirmar una orden vacía. Agrega al menos un producto.",
    "El cliente está inactivo y no puede confirmarse":
        "No se puede confirmar la orden porque el cliente está inactivo. Activa al cliente primero.",
    "El envío requiere una guía no vacía":
        "Escribe el número de guía para poder enviar la orden.",
    "La cancelación requiere un motivo no vacío":
        "Escribe el motivo para poder cancelar la orden.",
    "SKU obligatorio": "Escribe el código del producto que deseas agregar.",
    "La cantidad debe ser un entero positivo":
        "La cantidad de productos debe ser un número entero mayor que cero.",
}


def order_summary(order, products):
    """Consulta comercial sin nombres de clases, eventos ni estados internos."""
    quote = quote_discount(order)
    lines = [
        f"Orden {order.id}.",
        f"Estado: {STATES[order.status]}.",
        f"Cliente: {order.customer.id}.",
        f"Unidades: {order.units}.",
        f"Total antes del descuento: ${order.total.amount:,.2f} MXN.",
        f"Descuento ({quote.rate * 100:.0f}%): ${quote.discount.amount:,.2f} MXN.",
        f"Total a pagar: ${quote.payable.amount:,.2f} MXN.",
    ]
    if order.items:
        lines.append("Productos:")
        for item in order.items:
            name = products[item.sku]["nombre"]
            lines.append(f"{item.quantity} × {name}: ${item.subtotal.amount:,.2f} MXN.")
    else:
        lines.append("Esta orden todavía no tiene productos.")
    return "\n".join(lines)


def validation_message(exc):
    error = exc.errors()[0]
    kind = error["type"]
    field = error["loc"][-1] if error["loc"] else None
    labels = {
        "tracking_number": "el número de guía",
        "reason": "el motivo de cancelación",
        "sku": "el código del producto",
        "quantity": "la cantidad de productos",
    }
    if kind == "json_invalid":
        return "No se pudieron leer los datos enviados. Revisa el formato y vuelve a intentarlo."
    if kind == "extra_forbidden":
        return "Se enviaron datos adicionales. Completa únicamente los campos solicitados."
    if kind == "missing" and field in labels:
        return f"Falta {labels[field]}. Completa ese dato y vuelve a intentarlo."
    if field == "quantity":
        return "La cantidad de productos debe ser un número entero mayor que cero."
    if field in labels:
        return f"Escribe {labels[field]} como texto."
    return "Completa los datos solicitados para poder realizar la operación."


def create_app():
    api = FastAPI(
        title="TechStore U4", version="1.1.0",
        description="Gestión de órdenes con mensajes claros para el cliente.",
        default_response_class=PlainTextResponse,
    )
    api.state.orders = load_fixture()
    api.state.lock = RLock()
    products = {row["sku"]: row for row in rows("productos.csv")}

    @api.exception_handler(DomainException)
    async def domain_error(request: Request, exc: DomainException):
        status = 409 if isinstance(exc, InvalidOrderTransition) else 422
        if isinstance(exc, InvalidOrderTransition):
            action = request.url.path.rsplit("/", 1)[-1]
            with api.state.lock:
                order = api.state.orders[request.path_params["order_id"]]
                if action == "confirm" and order.status == OrderStatus.CONFIRMED:
                    message = "La orden ya está confirmada. No se puede confirmar otra vez."
                else:
                    message = f"La orden está {STATES[order.status]}. {TRANSITION_HELP[action]}"
        elif isinstance(exc, OrderItemLimitExceeded):
            message = "No se pueden agregar esos productos: una orden admite como máximo 20 unidades."
        else:
            message = DATA_MESSAGES.get(
                str(exc), "No se pudo completar la operación. Revisa los datos de la orden."
            )
        return PlainTextResponse(message, status_code=status)

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            message = {
                "Orden no existe.": "Orden no existe.",
                "Producto no existe.": "Producto no existe. Revisa su código en el catálogo.",
            }.get(str(exc.detail), "La página o la operación solicitada no existe.")
        elif exc.status_code == 405:
            message = "Esta operación no está disponible para la solicitud enviada."
        else:
            message = "No se pudo completar la solicitud. Revisa los datos e inténtalo nuevamente."
        return PlainTextResponse(message, status_code=exc.status_code, headers=exc.headers)

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return PlainTextResponse(validation_message(exc), status_code=422)

    def order_for(order_id):
        order = api.state.orders.get(order_id)
        if order is None:
            raise HTTPException(404, "Orden no existe.")
        return order

    def response_example(message):
        return {"content": {"text/plain": {"schema": {"type": "string"}, "example": message}}}

    errors = {
        404: {"description": "Orden o producto no encontrado", **response_example("Orden no existe.")},
        409: {"description": "La operación no se puede realizar en el estado actual",
              **response_example("La orden ya está confirmada. No se puede confirmar otra vez.")},
        422: {"description": "Falta un dato o no se cumple una condición de la orden",
              **response_example("No se puede confirmar una orden vacía. Agrega al menos un producto.")},
    }
    route_options = {"tags": ["Órdenes"], "responses": errors}

    @api.get("/orders/{order_id}", summary="Consultar una orden", **route_options)
    def get_order(order_id: str):
        with api.state.lock:
            return order_summary(order_for(order_id), products)

    @api.post("/orders/{order_id}/confirm", summary="Confirmar una orden", **route_options)
    def confirm_order(order_id: str):
        with api.state.lock:
            order_for(order_id).confirm()
            return "Orden confirmada."

    @api.post("/orders/{order_id}/ship", summary="Enviar una orden", **route_options)
    def ship_order(order_id: str, body: ShipBody):
        with api.state.lock:
            order_for(order_id).ship(body.tracking_number)
            return "Orden enviada."

    @api.post("/orders/{order_id}/cancel", summary="Cancelar una orden", **route_options)
    def cancel_order(order_id: str, body: CancelBody):
        with api.state.lock:
            order_for(order_id).cancel(body.reason)
            return "Orden cancelada."

    @api.post("/orders/{order_id}/deliver", summary="Registrar la entrega de una orden", **route_options)
    def deliver_order(order_id: str):
        with api.state.lock:
            order_for(order_id).deliver()
            return "Orden entregada."

    @api.post("/orders/{order_id}/return", summary="Registrar la devolución de una orden", **route_options)
    def return_order(order_id: str):
        with api.state.lock:
            order_for(order_id).return_order()
            return "Devolución de la orden registrada."

    @api.post("/orders/{order_id}/items", summary="Agregar un producto a una orden", **route_options)
    def add_item(order_id: str, body: ItemBody):
        with api.state.lock:
            order = order_for(order_id)
            if body.sku not in products:
                raise HTTPException(404, "Producto no existe.")
            price = Money(Decimal(products[body.sku]["precio_mxn"]))
            order.add_item(OrderItem(body.sku, body.quantity, price))
            return "Producto agregado a la orden."

    return api


app = create_app()
