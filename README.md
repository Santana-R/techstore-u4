# TechStore U4

Laboratorio de Componentes de Lógica de Negocio de FIME UANL. Implementa pedidos, reglas de descuento, una máquina de estados, eventos de dominio y una API REST sobre los CSV originales del paquete del alumno. La validación produjo 90 pruebas aprobadas y 15 de 15 escenarios verificados.

Integrantes: Roberto Santana Trujillo (2227084) e Isaías Leonardo Salazar Torres (2227016). Profesor: Miguel Ángel Gómez Marroquín.

Repositorio: https://github.com/Santana-R/techstore-u4

## Instalación

Requiere Python 3.11 o superior; se verificó con Python 3.12.14. Clona el repositorio y entra a su carpeta.

```bash
git clone https://github.com/Santana-R/techstore-u4.git
cd techstore-u4
python -m venv .venv
```

Activa el entorno según tu sistema. En macOS o Linux:

```bash
source .venv/bin/activate
```

En Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

En Windows CMD:

```bat
.venv\Scripts\activate.bat
```

Instala las versiones verificadas:

```bash
python -m pip install -r requirements.txt
```

Si PowerShell bloquea la activación, usa directamente `.venv\Scripts\python.exe` en lugar de `python`. En macOS o Linux, usa `.venv/bin/python`. La instalación ocurre dentro del entorno virtual.

## Ejecución y comprobación

Ejecuta desde la raíz del proyecto:

```bash
python cargar_csv.py
python ejecutar_escenarios.py
python -m pytest -q
python -m uvicorn app.api:app --reload
```

El cargador muestra los 16 pedidos en DRAFT. O001 debe tener 4 unidades y 2100.00 MXN. El ejecutor verifica E01 a E15 con datos nuevos por caso y actualiza `evidencias/escenarios.json` y `evidencias/bitacora.csv`. pytest debe informar 90 pruebas aprobadas.

Swagger se abre en http://127.0.0.1:8000/docs y el contrato OpenAPI está en http://127.0.0.1:8000/openapi.json. Las capturas del reporte usaron el puerto 8764; es la misma aplicación. Detén el servidor con Ctrl+C. Al reiniciarlo, todos los pedidos vuelven a DRAFT.

## Estructura

```text
app/domain.py          Entidades, VO, estados y eventos
app/specifications.py  Reglas AND, OR y NOT; descuentos
app/api.py             Adaptador HTTP y aplicación FastAPI
datos/                 Los cinco CSV originales del inge
tests/                 Dominio, reglas, API y escenarios
diagramas/             Draw.io editable y su PNG exportado
evidencias/            Bitácora, logs, OpenAPI y capturas
cargar_csv.py          Cargador original del paquete
ejecutar_escenarios.py  Ejecución reproducible de E01 a E15
requirements.txt       Versiones verificadas del entorno
```

`.venv`, `__pycache__` y `.pytest_cache` se excluyen del repositorio. Los CSV y el cargador se conservaron sin cambios.

## Reglas de negocio

- Money es inmutable, utiliza Decimal y rechaza importes negativos, no finitos y valores float. add exige la misma moneda. Los pedidos usan MXN.
- OrderItem es inmutable y exige SKU y cantidad entera positiva. El máximo es 20 unidades sumadas, aunque estén en uno o varios renglones.
- Descuento del 10 por ciento: cliente VIP, total bruto estrictamente mayor que 500 MXN, al menos 4 unidades y sin promoción.
- Descuento del 5 por ciento: total bruto estrictamente mayor que 5000 MXN y sin promoción. Si ambas reglas se cumplen, se aplica solo 10 por ciento.
- El descuento se calcula sobre el total bruto. El importe descontado se redondea a centavos con ROUND_HALF_UP; consultar el descuento no modifica el pedido ni genera eventos.
- Confirmar exige DRAFT, artículos y cliente activo. Enviar exige CONFIRMED y guía. Cancelar exige CONFIRMED y motivo. Entregar y devolver exigen SHIPPED.
- Toda transición válida registra un evento con pedido, cliente, total y fecha UTC. Un rechazo conserva el estado, los artículos y los eventos existentes.
- La existencia de productos es contexto del catálogo. No hay control de inventario, base de datos ni envío real de mensajes. Los objetos se guardan en memoria y los eventos se consultan en la respuesta de cada pedido.

## Endpoints

Todos los métodos devuelven 200 cuando la operación es válida. Los importes se serializan como cadenas decimales para conservar su representación.

| Método | Ruta | Entrada o resultado |
| --- | --- | --- |
| GET | /orders/{order_id} | Consulta el pedido y sus eventos |
| POST | /orders/{order_id}/confirm | Confirma sin cuerpo JSON |
| POST | /orders/{order_id}/ship | tracking_number como cadena |
| POST | /orders/{order_id}/cancel | reason como cadena |
| POST | /orders/{order_id}/deliver | Entrega desde SHIPPED |
| POST | /orders/{order_id}/return | Devuelve desde SHIPPED |
| POST | /orders/{order_id}/items | sku y quantity; precio del CSV |

404 identifica pedido o SKU inexistente; 409 indica una transición prohibida; 422 indica datos o una regla de negocio inválidos. Los cuerpos rechazan campos adicionales y cantidades que no sean enteros positivos.

## Ejemplo en Swagger

1. En POST /orders/{order_id}/confirm, pulsa Try it out y escribe O013. Execute devuelve 200, CONFIRMED y OrderConfirmed.
2. Ejecuta otra vez el mismo pedido: devuelve 409 y conserva un solo evento.
3. Usa O007 para comprobar 422 por pedido vacío y NOEXISTE para comprobar 404.
4. Reinicia el servidor para repetir los casos desde DRAFT. Las pruebas automáticas crean una aplicación independiente por caso.

## Evidencias y diagrama

`evidencias/carga.txt`, `pytest.txt` y `escenarios.txt` conservan la salida real de ejecución. Sus capturas se muestran en visores locales; los HTML identifican expresamente el comando y el archivo de origen. Las imágenes swagger_200, swagger_404, swagger_409 y swagger_422 son capturas reales de /docs.

El archivo `diagramas/techstore_estados.drawio` es editable en https://app.diagrams.net. Su PNG se exportó desde draw.io e incluye una copia editable del diagrama. Los recortes del reporte solo encuadran los resultados; las capturas completas se conservan en el repositorio.

El reporte único se encuentra en `reporte/2227084_2227016_AF4_CLNEG_TechStore.pdf`. Incluye los ocho entregables, la bitácora completa, las cinco preguntas resueltas y la reflexión.

## Referencias

- Material del curso: práctica guiada TechStore, manual ilustrado U4 y paquete de CSV y cargador proporcionados por el profesor.
- FastAPI: https://fastapi.tiangolo.com/tutorial/testing/ y https://fastapi.tiangolo.com/tutorial/handling-errors/
- pytest: https://docs.pytest.org/en/stable/how-to/parametrize.html
- Python Decimal: https://docs.python.org/3/library/decimal.html
