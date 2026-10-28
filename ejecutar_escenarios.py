"""Ejecuta E01-E15 sobre los CSV originales y guarda evidencia reproducible."""
import csv
import json
from pathlib import Path
from decimal import Decimal
from app.domain import DomainException, Money, OrderItem
from app.specifications import quote_discount
from cargar_csv import load_fixture, rows

EXPECTED = {
    "E01": ("DRAFT", [], None, "10"),
    "E02": ("DRAFT", [], None, "0"),
    "E03": ("DRAFT", [], "InvalidOrderData", None),
    "E04": ("DRAFT", [], None, "0"),
    "E05": ("DRAFT", [], None, "5"),
    "E06": ("DRAFT", [], "InvalidOrderData", None),
    "E07": ("CONFIRMED", ["OrderConfirmed"], None, None),
    "E08": ("DRAFT", [], "OrderItemLimitExceeded", None),
    "E09": ("DRAFT", [], None, "0"),
    "E10": ("DRAFT", [], None, "0"),
    "E11": ("CONFIRMED", ["OrderConfirmed"], "InvalidOrderData", None),
    "E12": ("CONFIRMED", ["OrderConfirmed"], "InvalidOrderTransition", None),
    "E13": ("SHIPPED", ["OrderConfirmed", "OrderShipped"], "InvalidOrderTransition", None),
    "E14": ("RETURNED", ["OrderConfirmed", "OrderShipped", "OrderReturned"], None, None),
    "E15": ("DELIVERED", ["OrderConfirmed", "OrderShipped", "OrderDelivered"], None, None),
}


def run_case(case_id):
    source = next(x for x in rows("escenarios.csv") if x["caso_id"] == case_id)
    order = load_fixture()[source["pedido_id"]]
    initial = {"status": order.status.value, "units": order.units,
               "total": f"{order.total.amount:.2f}",
               "customer": order.customer.id, "vip": order.customer.is_vip,
               "active": order.customer.active, "promotion": order.has_promotion}
    error = None
    message = ""
    steps = []

    def act(label, method, *args):
        before = (order.status, order.items, order.events)
        try:
            method(*args)
        except DomainException as exc:
            assert (order.status, order.items, order.events) == before, "Un rechazo modificó el agregado"
            steps.append({"operation": label, "result": type(exc).__name__,
                          "status": order.status.value, "new_event": None})
            raise
        new_event = order.events[-1].name if len(order.events) > len(before[2]) else None
        steps.append({"operation": label, "result": "aceptada", "status": order.status.value,
                      "new_event": new_event})

    try:
        if "evaluar_descuento" == source["accion"]:
            before = (order.status, order.items, order.events)
            quote_discount(order)
            assert before == (order.status, order.items, order.events)
            steps.append({"operation": "evaluar_descuento", "result": "evaluada sin modificar el pedido",
                          "status": order.status.value, "new_event": None})
        elif case_id == "E08":
            act("agregar SKU003 x2", order.add_item, OrderItem("SKU003", 2, Money(Decimal("120"))))
        else:
            act("confirmar", order.confirm)
            if case_id == "E11":
                act("enviar sin guía", order.ship, "")
            elif case_id == "E12":
                act("confirmar de nuevo", order.confirm)
            elif case_id in {"E13", "E14", "E15"}:
                act("enviar con guía", order.ship, f"GUIA-{case_id}")
                if case_id == "E13":
                    act("cancelar después del envío", order.cancel, "Solicitud del cliente")
                elif case_id == "E14":
                    act("devolver desde SHIPPED", order.return_order)
                else:
                    act("entregar desde SHIPPED", order.deliver)
    except DomainException as exc:
        error, message = type(exc).__name__, str(exc)

    quote = quote_discount(order)
    rate = f"{quote.rate * 100:.0f}"
    expected_status, expected_events, expected_error, expected_rate = EXPECTED[case_id]
    actual_events = [e.name for e in order.events]
    assert order.status.value == expected_status
    assert actual_events == expected_events
    assert error == expected_error
    if expected_rate is not None:
        assert rate == expected_rate
    return {"case": case_id, "order": order.id, "initial": initial,
            "operation": source["accion"], "expected": source["objetivo"],
            "status": order.status.value, "units": order.units,
            "total": f"{order.total.amount:.2f}", "rate": rate,
            "discount": f"{quote.discount.amount:.2f}",
            "payable": f"{quote.payable.amount:.2f}", "error": error,
            "message": message, "events": actual_events, "steps": steps,
            "test": f"tests/test_scenarios.py::test_escenario[{case_id}]", "passed": True}


def main():
    results = [run_case(x["caso_id"]) for x in rows("escenarios.csv")]
    destination = Path(__file__).resolve().parent / "evidencias"
    destination.mkdir(exist_ok=True)
    (destination / "escenarios.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    with (destination / "bitacora.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["caso", "pedido", "precondiciones", "operacion", "resultado", "eventos", "prueba"])
        for r in results:
            writer.writerow([r["case"], r["order"], json.dumps(r["initial"], ensure_ascii=False),
                             r["operation"], f'{r["status"]}; {r["error"] or r["rate"] + "%"}',
                             ", ".join(r["events"]) or "Ninguno", r["test"]])
    for r in results:
        print(f'{r["case"]} {r["order"]} PASS  {r["status"]:10}  {r["error"] or r["rate"] + "%"}')
    print(f"\n{len(results)}/15 escenarios verificados con fixtures independientes")


if __name__ == "__main__":
    main()
