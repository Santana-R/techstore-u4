from decimal import Decimal
import pytest
from app.domain import Customer, Money, Order, OrderItem
from app.specifications import (quote_discount, MinimumAmountSpec, VIPCustomerSpec,
                                MinimumUnitsSpec, ActivePromotionSpec, TEN_PERCENT,
                                FIVE_PERCENT, ANY_DISCOUNT)
from cargar_csv import load_fixture


def make_order(total, quantity, vip, promotion=False):
    order = Order(Customer("C", vip), "O", promotion)
    order.add_item(OrderItem("A", quantity, Money(Decimal(total) / quantity)))
    return order


@pytest.mark.parametrize("total,quantity,vip,promotion,rate", [
    ("500", 4, True, False, "0"), ("500.01", 4, True, False, "0.10"),
    ("5000", 1, False, False, "0"), ("5000.01", 1, False, False, "0.05"),
    ("6000", 4, True, False, "0.10"), ("6000", 4, True, True, "0"),
    ("6000", 1, False, True, "0"), ("1500", 3, True, False, "0"),
    ("2100", 4, True, False, "0.10")])
def test_fronteras_prioridad_y_promocion(total, quantity, vip, promotion, rate):
    order = make_order(total, quantity, vip, promotion)
    before = (order.status, order.items, order.events, order.total)
    assert quote_discount(order).rate == Decimal(rate)
    assert before == (order.status, order.items, order.events, order.total)


def test_and_or_not_y_componentes_independientes():
    order = load_fixture()["O001"]
    assert MinimumAmountSpec(Decimal("500")).is_satisfied_by(order)
    assert VIPCustomerSpec().is_satisfied_by(order)
    assert MinimumUnitsSpec(4).is_satisfied_by(order)
    assert not ActivePromotionSpec().is_satisfied_by(order)
    assert TEN_PERCENT.is_satisfied_by(order)
    assert not FIVE_PERCENT.is_satisfied_by(order)
    assert ANY_DISCOUNT.is_satisfied_by(order)
    non_vip = load_fixture()["O006"]
    assert not TEN_PERCENT.is_satisfied_by(non_vip)
    assert FIVE_PERCENT.is_satisfied_by(non_vip) and ANY_DISCOUNT.is_satisfied_by(non_vip)


def test_importes_neto_y_redondeo():
    quote = quote_discount(load_fixture()["O001"])
    assert (quote.discount.amount, quote.payable.amount) == (Decimal("210"), Decimal("1890"))
    quote = quote_discount(load_fixture()["O006"])
    assert (quote.discount.amount, quote.payable.amount) == (Decimal("900"), Decimal("17100"))
    assert quote_discount(make_order("500.05", 4, True)).discount.amount == Decimal("50.01")
