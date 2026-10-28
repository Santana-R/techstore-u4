import pytest
from fastapi.testclient import TestClient
from app.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def test_consulta_y_desglose_decimal(client):
    result = client.get("/orders/O001")
    assert result.status_code == 200
    data = result.json()
    assert (data["total"], data["discount"], data["payable"]) == ("2100.00", "210.00", "1890.00")
    assert data["status"] == "DRAFT" and data["events"] == []


@pytest.mark.parametrize("path", ["/orders/NOEXISTE", "/orders/NOEXISTE/confirm"])
def test_http_404(client, path):
    result = client.get(path) if path.endswith("NOEXISTE") else client.post(path)
    assert result.status_code == 404


def test_confirmar_dos_veces_http_409_sin_evento_extra(client):
    assert client.post("/orders/O013/confirm").status_code == 200
    before = client.get("/orders/O013").json()
    assert client.post("/orders/O013/confirm").status_code == 409
    assert client.get("/orders/O013").json() == before


@pytest.mark.parametrize("order_id", ["O003", "O007"])
def test_http_422_cliente_inactivo_y_pedido_vacio(client, order_id):
    before = client.get(f"/orders/{order_id}").json()
    assert client.post(f"/orders/{order_id}/confirm").status_code == 422
    assert client.get(f"/orders/{order_id}").json() == before


def test_envio_guia_obligatoria_y_cancelacion_prohibida(client):
    assert client.post("/orders/O014/confirm").status_code == 200
    before = client.get("/orders/O014").json()
    assert client.post("/orders/O014/ship", json={"tracking_number": " "}).status_code == 422
    assert client.get("/orders/O014").json() == before
    assert client.post("/orders/O014/ship", json={"tracking_number": "GUIA"}).status_code == 200
    before = client.get("/orders/O014").json()
    assert client.post("/orders/O014/cancel", json={"reason": "Solicitud"}).status_code == 409
    assert client.get("/orders/O014").json() == before


@pytest.mark.parametrize("action,expected", [("deliver", "DELIVERED"), ("return", "RETURNED")])
def test_finalizacion_valida(client, action, expected):
    client.post("/orders/O015/confirm")
    client.post("/orders/O015/ship", json={"tracking_number": "GUIA"})
    result = client.post(f"/orders/O015/{action}")
    assert result.status_code == 200 and result.json()["status"] == expected
    assert len(result.json()["events"]) == 3


def test_cancelacion_valida_y_motivo(client):
    client.post("/orders/O012/confirm")
    assert client.post("/orders/O012/cancel", json={"reason": ""}).status_code == 422
    result = client.post("/orders/O012/cancel", json={"reason": "Solicitud del cliente"})
    assert result.status_code == 200 and result.json()["status"] == "CANCELLED"
    assert result.json()["events"][-1]["reason"] == "Solicitud del cliente"


def test_limite_unidades_y_validacion_json(client):
    before = client.get("/orders/O009").json()
    assert client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 2}).status_code == 422
    assert client.get("/orders/O009").json() == before
    for quantity in [True, 1.5, "2", 0]:
        assert client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": quantity}).status_code == 422
    assert client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 1}).json()["units"] == 20


def test_docs_openapi_y_aislamiento(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/orders/{order_id}/confirm" in schema["paths"]
    assert "post" in schema["paths"]["/orders/{order_id}/confirm"]
    client.post("/orders/O001/confirm")
    with TestClient(create_app()) as fresh:
        assert fresh.get("/orders/O001").json()["status"] == "DRAFT"
