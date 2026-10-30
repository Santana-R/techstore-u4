import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.domain import OrderStatus


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def assert_message(response, status, message):
    assert response.status_code == status
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == message


def snapshot(client, order_id):
    order = client.app.state.orders[order_id]
    return order.status, order.items, order.events


@pytest.mark.parametrize("order_id,amounts", [
    ("O001", ("2,100.00", "210.00", "1,890.00")),
    ("O006", ("18,000.00", "900.00", "17,100.00")),
])
def test_consulta_en_espanol_y_desglose_decimal(client, order_id, amounts):
    result = client.get(f"/orders/{order_id}")
    assert result.status_code == 200
    assert result.headers["content-type"] == "text/plain; charset=utf-8"
    assert f"Orden {order_id}." in result.text
    assert "Estado: en preparación." in result.text
    assert f"Total antes del descuento: ${amounts[0]} MXN." in result.text
    assert f"Total a pagar: ${amounts[2]} MXN." in result.text
    assert f"${amounts[1]} MXN." in result.text
    assert "Productos:" in result.text
    for internal in ["DRAFT", "OrderConfirmed", '"events"', '"customer_id"']:
        assert internal not in result.text


@pytest.mark.parametrize("path", ["/orders/NOEXISTE", "/orders/NOEXISTE/confirm"])
def test_http_404_con_mensaje_sencillo(client, path):
    result = client.get(path) if path.endswith("NOEXISTE") else client.post(path)
    assert_message(result, 404, "Orden no existe.")


def test_confirmar_dos_veces_http_409_sin_evento_extra(client):
    assert_message(client.post("/orders/O013/confirm"), 200, "Orden confirmada.")
    before = snapshot(client, "O013")
    assert before[0] == OrderStatus.CONFIRMED
    assert len(before[2]) == 1 and before[2][0].name == "OrderConfirmed"
    assert_message(client.post("/orders/O013/confirm"), 409,
                   "La orden ya está confirmada. No se puede confirmar otra vez.")
    assert snapshot(client, "O013") == before


@pytest.mark.parametrize("order_id,message", [
    ("O003", "No se puede confirmar la orden porque el cliente está inactivo. Activa al cliente primero."),
    ("O007", "No se puede confirmar una orden vacía. Agrega al menos un producto."),
])
def test_http_422_cliente_inactivo_y_orden_vacia(client, order_id, message):
    before = snapshot(client, order_id)
    assert_message(client.post(f"/orders/{order_id}/confirm"), 422, message)
    assert snapshot(client, order_id) == before


def test_envio_guia_obligatoria_y_cancelacion_prohibida(client):
    client.post("/orders/O014/confirm")
    before = snapshot(client, "O014")
    assert_message(client.post("/orders/O014/ship", json={"tracking_number": " "}), 422,
                   "Escribe el número de guía para poder enviar la orden.")
    assert snapshot(client, "O014") == before
    assert_message(client.post("/orders/O014/ship", json={"tracking_number": "GUIA"}),
                   200, "Orden enviada.")
    before = snapshot(client, "O014")
    assert_message(client.post("/orders/O014/cancel", json={"reason": "Solicitud"}), 409,
                   "La orden está enviada. Solo se puede cancelar una orden confirmada que aún no se haya enviado.")
    assert snapshot(client, "O014") == before


@pytest.mark.parametrize("action,expected,message", [
    ("deliver", OrderStatus.DELIVERED, "Orden entregada."),
    ("return", OrderStatus.RETURNED, "Devolución de la orden registrada."),
])
def test_finalizacion_valida(client, action, expected, message):
    client.post("/orders/O015/confirm")
    client.post("/orders/O015/ship", json={"tracking_number": "GUIA"})
    assert_message(client.post(f"/orders/O015/{action}"), 200, message)
    order = client.app.state.orders["O015"]
    assert order.status == expected and len(order.events) == 3
    assert f"Estado: {'entregada' if action == 'deliver' else 'devuelta'}." in client.get("/orders/O015").text


def test_cancelacion_valida_y_motivo(client):
    client.post("/orders/O012/confirm")
    before = snapshot(client, "O012")
    assert_message(client.post("/orders/O012/cancel", json={"reason": ""}), 422,
                   "Escribe el motivo para poder cancelar la orden.")
    assert snapshot(client, "O012") == before
    assert_message(client.post("/orders/O012/cancel", json={"reason": "Solicitud del cliente"}),
                   200, "Orden cancelada.")
    order = client.app.state.orders["O012"]
    assert order.status == OrderStatus.CANCELLED
    assert order.events[-1].reason == "Solicitud del cliente"


def test_limite_unidades_sin_cambios_parciales(client):
    before = snapshot(client, "O009")
    assert_message(client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 2}), 422,
                   "No se pueden agregar esos productos: una orden admite como máximo 20 unidades.")
    assert snapshot(client, "O009") == before
    assert_message(client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 1}),
                   200, "Producto agregado a la orden.")
    assert client.app.state.orders["O009"].units == 20


@pytest.mark.parametrize("quantity", [True, 1.5, "2", 0, -1, None])
def test_cantidad_invalida_sin_errores_tecnicos(client, quantity):
    before = snapshot(client, "O009")
    assert_message(client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": quantity}),
                   422, "La cantidad de productos debe ser un número entero mayor que cero.")
    assert snapshot(client, "O009") == before


@pytest.mark.parametrize("action,body,message", [
    ("ship", {}, "Falta el número de guía. Completa ese dato y vuelve a intentarlo."),
    ("cancel", {}, "Falta el motivo de cancelación. Completa ese dato y vuelve a intentarlo."),
    ("items", {"sku": "SKU003"}, "Falta la cantidad de productos. Completa ese dato y vuelve a intentarlo."),
    ("items", {"quantity": 1}, "Falta el código del producto. Completa ese dato y vuelve a intentarlo."),
    ("ship", {"tracking_number": 123}, "Escribe el número de guía como texto."),
    ("cancel", {"reason": None}, "Escribe el motivo de cancelación como texto."),
    ("items", {"sku": 123, "quantity": 1}, "Escribe el código del producto como texto."),
    ("items", {"sku": "SKU003", "quantity": 1, "precio": 1},
     "Se enviaron datos adicionales. Completa únicamente los campos solicitados."),
])
def test_datos_faltantes_o_invalidos_en_espanol(client, action, body, message):
    before = snapshot(client, "O012")
    assert_message(client.post(f"/orders/O012/{action}", json=body), 422, message)
    assert snapshot(client, "O012") == before


def test_cuerpo_ilegible_o_ausente(client):
    assert_message(client.post("/orders/O012/ship", content='{',
                               headers={"content-type": "application/json"}), 422,
                   "No se pudieron leer los datos enviados. Revisa el formato y vuelve a intentarlo.")
    assert_message(client.post("/orders/O012/ship"), 422,
                   "Completa los datos solicitados para poder realizar la operación.")


def test_producto_desconocido(client):
    before = snapshot(client, "O001")
    assert_message(client.post("/orders/O001/items", json={"sku": "NOEXISTE", "quantity": 1}),
                   404, "Producto no existe. Revisa su código en el catálogo.")
    assert snapshot(client, "O001") == before


@pytest.mark.parametrize("action,body,required", [
    ("ship", {"tracking_number": "GUIA"}, "Para enviar una orden, primero debe estar confirmada."),
    ("cancel", {"reason": "Prueba"}, "Solo se puede cancelar una orden confirmada que aún no se haya enviado."),
    ("deliver", None, "Para registrar la entrega, la orden debe estar enviada."),
    ("return", None, "Solo se puede devolver una orden que esté enviada."),
])
def test_estado_incorrecto_explicado_segun_operacion(client, action, body, required):
    before = snapshot(client, "O001")
    assert_message(client.post(f"/orders/O001/{action}", json=body), 409,
                   f"La orden está en preparación. {required}")
    assert snapshot(client, "O001") == before


def test_agregar_productos_despues_de_confirmar_no_dice_confirmar_de_nuevo(client):
    client.post("/orders/O001/confirm")
    before = snapshot(client, "O001")
    assert_message(client.post("/orders/O001/items", json={"sku": "SKU003", "quantity": 1}), 409,
                   "La orden está confirmada. Solo se pueden agregar productos mientras la orden esté en preparación.")
    assert snapshot(client, "O001") == before


def test_confirmar_orden_enviada_describe_el_estado_real(client):
    client.post("/orders/O001/confirm")
    client.post("/orders/O001/ship", json={"tracking_number": "GUIA"})
    before = snapshot(client, "O001")
    assert_message(client.post("/orders/O001/confirm"), 409,
                   "La orden está enviada. Solo se puede confirmar una orden que esté en preparación.")
    assert snapshot(client, "O001") == before


def test_ruta_y_metodo_inexistentes(client):
    assert_message(client.get("/no-existe"), 404, "La página o la operación solicitada no existe.")
    result = client.get("/orders/O001/confirm")
    assert_message(result, 405, "Esta operación no está disponible para la solicitud enviada.")
    assert result.headers["allow"] == "POST"


def test_docs_openapi_y_aislamiento(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/orders/{order_id}/confirm" in schema["paths"]
    for path in schema["paths"].values():
        for operation in path.values():
            for status in ["200", "404", "409", "422"]:
                assert set(operation["responses"][status]["content"]) == {"text/plain"}
    client.post("/orders/O001/confirm")
    with TestClient(create_app()) as fresh:
        assert "Estado: en preparación." in fresh.get("/orders/O001").text
