"""Dominio puro: sin FastAPI, archivos ni persistencia."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class DomainException(Exception):
    """Una regla de negocio impide completar la operación."""


class InvalidOrderData(DomainException):
    pass


class InvalidOrderTransition(DomainException):
    pass


class OrderItemLimitExceeded(DomainException):
    pass


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "MXN"

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise InvalidOrderData("El importe debe construirse con Decimal")
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidOrderData("El importe debe ser finito y no negativo")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise InvalidOrderData("Moneda inválida")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("No se pueden sumar monedas distintas")
        return Money(self.amount + other.amount, self.currency)


@dataclass(frozen=True)
class Customer:
    id: str
    is_vip: bool = False
    active: bool = True

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise InvalidOrderData("El cliente requiere identificador")
        if type(self.is_vip) is not bool or type(self.active) is not bool:
            raise InvalidOrderData("VIP y activo deben ser booleanos")


@dataclass(frozen=True)
class OrderItem:
    sku: str
    quantity: int
    unit_price: Money

    def __post_init__(self):
        if not isinstance(self.sku, str) or not self.sku.strip():
            raise InvalidOrderData("SKU obligatorio")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise InvalidOrderData("La cantidad debe ser un entero positivo")
        if not isinstance(self.unit_price, Money):
            raise InvalidOrderData("El precio debe ser Money")

    @property
    def subtotal(self) -> Money:
        return Money(self.unit_price.amount * self.quantity, self.unit_price.currency)


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


@dataclass(frozen=True)
class DomainEvent:
    name: str
    order_id: str
    customer_id: str
    total: Money
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tracking_number: str | None = None
    reason: str | None = None


class Order:
    """Aggregate Root. Solo los métodos de negocio cambian su ciclo de vida."""

    def __init__(self, customer: Customer, id: str, has_promotion: bool = False):
        if not isinstance(customer, Customer) or not isinstance(id, str) or not id.strip():
            raise InvalidOrderData("Pedido y cliente requieren identificadores válidos")
        if type(has_promotion) is not bool:
            raise InvalidOrderData("La promoción debe ser booleana")
        self._customer = customer
        self._id = id
        self._has_promotion = has_promotion
        self._status = OrderStatus.DRAFT
        self._items: list[OrderItem] = []
        self._events: list[DomainEvent] = []

    @property
    def id(self):
        return self._id

    @property
    def customer(self):
        return self._customer

    @property
    def has_promotion(self):
        return self._has_promotion

    @property
    def status(self):
        return self._status

    @property
    def items(self):
        return tuple(self._items)

    @property
    def events(self):
        return tuple(self._events)

    @property
    def units(self):
        return sum(item.quantity for item in self._items)

    @property
    def total(self):
        """Importe bruto antes de descuentos; nunca depende de la política."""
        return Money(sum((item.subtotal.amount for item in self._items), Decimal("0")))

    def _require(self, state: OrderStatus):
        if self._status != state:
            raise InvalidOrderTransition(f"Requiere {state.value}; estado actual {self._status.value}")

    def add_item(self, item: OrderItem):
        self._require(OrderStatus.DRAFT)
        if not isinstance(item, OrderItem) or item.unit_price.currency != "MXN":
            raise InvalidOrderData("El pedido solo admite artículos con precio MXN")
        if self.units + item.quantity > 20:
            raise OrderItemLimitExceeded("Máximo 20 unidades por pedido")
        self._items.append(item)

    def _record(self, status: OrderStatus, name: str, **details):
        # Construir el evento antes de modificar el agregado evita cambios parciales.
        event = DomainEvent(name, self.id, self.customer.id, self.total, **details)
        self._status = status
        self._events.append(event)

    def confirm(self):
        self._require(OrderStatus.DRAFT)

        if not self._items:
            raise InvalidOrderData("El pedido no contiene artículos")

        if not self.customer.active:
            raise InvalidOrderData("El cliente está inactivo y no puede confirmarse")        

        self._record(OrderStatus.CONFIRMED, "OrderConfirmed")

    def ship(self, tracking_number: str):
        self._require(OrderStatus.CONFIRMED)
        if not isinstance(tracking_number, str) or not tracking_number.strip():
            raise InvalidOrderData("El envío requiere una guía no vacía")
        self._record(OrderStatus.SHIPPED, "OrderShipped", tracking_number=tracking_number.strip())

    def cancel(self, reason: str):
        self._require(OrderStatus.CONFIRMED)
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidOrderData("La cancelación requiere un motivo no vacío")
        self._record(OrderStatus.CANCELLED, "OrderCancelled", reason=reason.strip())

    def deliver(self):
        self._require(OrderStatus.SHIPPED)
        self._record(OrderStatus.DELIVERED, "OrderDelivered")

    def return_order(self):
        # Regla didáctica explícita: devolución desde SHIPPED.
        self._require(OrderStatus.SHIPPED)
        self._record(OrderStatus.RETURNED, "OrderReturned")
