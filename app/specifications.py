"""Specifications puras y cotización decimal sin modificar el pedido."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from app.domain import Money, Order


class Specification:
    def is_satisfied_by(self, order: Order) -> bool:
        raise NotImplementedError

    def __and__(self, other):
        return AndSpec(self, other)

    def __or__(self, other):
        return OrSpec(self, other)

    def __invert__(self):
        return NotSpec(self)


@dataclass(frozen=True)
class AndSpec(Specification):
    left: Specification
    right: Specification

    def is_satisfied_by(self, order):
        return self.left.is_satisfied_by(order) and self.right.is_satisfied_by(order)


@dataclass(frozen=True)
class OrSpec(Specification):
    left: Specification
    right: Specification

    def is_satisfied_by(self, order):
        return self.left.is_satisfied_by(order) or self.right.is_satisfied_by(order)


@dataclass(frozen=True)
class NotSpec(Specification):
    specification: Specification

    def is_satisfied_by(self, order):
        return not self.specification.is_satisfied_by(order)


@dataclass(frozen=True)
class MinimumAmountSpec(Specification):
    threshold: Decimal

    def is_satisfied_by(self, order):
        return order.total.amount > self.threshold


class VIPCustomerSpec(Specification):
    def is_satisfied_by(self, order):
        return order.customer.is_vip


@dataclass(frozen=True)
class MinimumUnitsSpec(Specification):
    minimum: int

    def is_satisfied_by(self, order):
        return order.units >= self.minimum


class ActivePromotionSpec(Specification):
    def is_satisfied_by(self, order):
        return order.has_promotion


TEN_PERCENT = (MinimumAmountSpec(Decimal("500")) & VIPCustomerSpec()
               & MinimumUnitsSpec(4) & ~ActivePromotionSpec())
FIVE_PERCENT = MinimumAmountSpec(Decimal("5000")) & ~ActivePromotionSpec()
ANY_DISCOUNT = TEN_PERCENT | FIVE_PERCENT


@dataclass(frozen=True)
class DiscountQuote:
    rate: Decimal
    discount: Money
    payable: Money


def quote_discount(order: Order) -> DiscountQuote:
    # La prioridad evita sumar ambos descuentos cuando coinciden las reglas.
    if not ANY_DISCOUNT.is_satisfied_by(order):
        rate = Decimal("0")
    elif TEN_PERCENT.is_satisfied_by(order):
        rate = Decimal("0.10")
    else:
        rate = Decimal("0.05")
    discount = (order.total.amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return DiscountQuote(rate, Money(discount), Money(order.total.amount - discount))
