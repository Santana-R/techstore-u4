from dataclasses import FrozenInstanceError
from decimal import Decimal
import pytest
from app.domain import (Money, Customer, Order, OrderItem, OrderStatus,
                        InvalidOrderData, InvalidOrderTransition, OrderItemLimitExceeded)
from cargar_csv import load_fixture


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "-Infinity"])
def test_money_rechaza_importes_invalidos(amount):
    with pytest.raises(InvalidOrderData):
        Money(Decimal(amount))


def test_money_rechaza_float_y_es_inmutable():
    with pytest.raises(InvalidOrderData):
        Money(0.1)
    money = Money(Decimal("100"))
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("5")


def test_suma_decimal_inmutable_y_moneda():
    first = Money(Decimal("0.1"))
    assert first.add(Money(Decimal("0.2"))).amount == Decimal("0.3")
    assert first.amount == Decimal("0.1")
    with pytest.raises(InvalidOrderData):
        first.add(Money(Decimal("1"), "USD"))
    assert OrderItem("A", 2, Money(Decimal("3"), "USD")).subtotal.currency == "USD"


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2"])
def test_cantidad_entera_positiva(quantity):
    with pytest.raises(InvalidOrderData):
        OrderItem("A", quantity, Money(Decimal("1")))


def test_carga_16_pedidos_y_calculos_manuales():
    orders = load_fixture()
    assert len(orders) == 16
    assert all(o.status == OrderStatus.DRAFT and not o.events for o in orders.values())
    assert (orders["O001"].units, orders["O001"].total.amount) == (4, Decimal("2100"))
    assert (orders["O006"].units, orders["O006"].total.amount) == (1, Decimal("18000"))
    assert (orders["O010"].units, orders["O010"].total.amount) == (2, Decimal("500"))


def test_limite_suma_cantidades_no_renglones():
    order = Order(Customer("C"), "O")
    for sku in ["A", "B"]:
        order.add_item(OrderItem(sku, 10, Money(Decimal("1"))))
    before = order.items
    assert order.units == 20 and len(order.items) == 2
    with pytest.raises(OrderItemLimitExceeded):
        order.add_item(OrderItem("C", 1, Money(Decimal("1"))))
    assert order.items == before and order.units == 20


def test_no_se_implementa_control_de_inventario():
    order = Order(Customer("C"), "O")
    order.add_item(OrderItem("SKU008", 20, Money(Decimal("18000"))))
    assert order.units == 20  # El catálogo tiene 7; existencia solo es contexto.


def test_no_admite_moneda_extranjera_ni_mutacion_externa():
    order = load_fixture()["O001"]
    with pytest.raises(InvalidOrderData):
        order.add_item(OrderItem("A", 1, Money(Decimal("1"), "USD")))
    with pytest.raises(AttributeError):
        order.status = OrderStatus.SHIPPED
    with pytest.raises(AttributeError):
        order.items.append(OrderItem("A", 1, Money(Decimal("1"))))


def at_state(state):
    order = load_fixture()["O001"]
    if state != "DRAFT":
        order.confirm()
    if state in {"SHIPPED", "DELIVERED", "RETURNED"}:
        order.ship("GUIA-TEST")
    if state == "CANCELLED":
        order.cancel("Prueba")
    if state == "DELIVERED":
        order.deliver()
    if state == "RETURNED":
        order.return_order()
    return order


ALLOWED = {("DRAFT", "confirm"): ("CONFIRMED", "OrderConfirmed"),
           ("CONFIRMED", "ship"): ("SHIPPED", "OrderShipped"),
           ("CONFIRMED", "cancel"): ("CANCELLED", "OrderCancelled"),
           ("SHIPPED", "deliver"): ("DELIVERED", "OrderDelivered"),
           ("SHIPPED", "return_order"): ("RETURNED", "OrderReturned")}


@pytest.mark.parametrize("state", [x.value for x in OrderStatus])
@pytest.mark.parametrize("action", ["confirm", "ship", "cancel", "deliver", "return_order"])
def test_matriz_completa_de_transiciones(state, action):
    order = at_state(state)
    before = (order.status, order.items, order.events)
    args = ("GUIA-TEST",) if action == "ship" else (("Prueba",) if action == "cancel" else ())
    if (state, action) in ALLOWED:
        getattr(order, action)(*args)
        expected_status, expected_event = ALLOWED[state, action]
        assert order.status.value == expected_status
        assert len(order.events) == len(before[2]) + 1
        event = order.events[-1]
        assert event.name == expected_event and event.order_id == order.id
        assert event.customer_id == order.customer.id and event.total == order.total
        assert event.occurred_at.tzinfo is not None
    else:
        with pytest.raises(InvalidOrderTransition):
            getattr(order, action)(*args)
        assert before == (order.status, order.items, order.events)


@pytest.mark.parametrize("action", ["ship", "cancel"])
@pytest.mark.parametrize("value", ["", "   ", None])
def test_guia_y_motivo_obligatorios_sin_cambios_parciales(action, value):
    order = at_state("CONFIRMED")
    before = (order.status, order.events)
    with pytest.raises(InvalidOrderData):
        getattr(order, action)(value)
    assert before == (order.status, order.events)


def test_agregar_despues_de_confirmar_falla():
    order = at_state("CONFIRMED")
    before = (order.items, order.events)
    with pytest.raises(InvalidOrderTransition):
        order.add_item(OrderItem("A", 1, Money(Decimal("1"))))
    assert before == (order.items, order.events)
