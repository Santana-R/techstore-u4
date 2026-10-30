# TechStore U4

Implementa pedidos, reglas de descuento, una máquina de estados, eventos de dominio y una API REST sobre los CSV originales. La validación produjo 114 pruebas aprobadas y 15 de 15 escenarios verificados.

Integrantes: Roberto Santana Trujillo (2227084) e Isaías Leonardo Salazar Torres (2227016).

Repositorio: https://github.com/Santana-R/techstore-u4

## Instalación

Requiere Python 3.11 o superior; se verificó con Python 3.12.14. Clona el repositorio y entra a su carpeta.

```bash
git clone https://github.com/Santana-R/techstore-u4
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

El cargador muestra los 16 pedidos en DRAFT. O001 debe tener 4 unidades y 2100.00 MXN. El ejecutor verifica E01 a E15 con datos nuevos por caso y actualiza `evidencias/escenarios.json` y `evidencias/bitacora.csv`. pytest debe informar 114 pruebas aprobadas.

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
- La existencia de productos es contexto del catálogo. No hay control de inventario, base de datos ni envío real de mensajes. Los objetos y los eventos se guardan en memoria. Las pruebas verifican los eventos directamente en el dominio; las respuestas al cliente muestran mensajes e información comercial en español.

## Endpoints

Todos los métodos devuelven 200 cuando la operación es válida. El cuerpo de la respuesta es texto en español (`text/plain; charset=utf-8`), tanto en las operaciones exitosas como en los errores. Las acciones devuelven únicamente su mensaje; la consulta presenta el estado, las unidades, los productos y los importes con etiquetas claras. Los importes se calculan con Decimal y se muestran con dos decimales.

| Método | Ruta | Entrada o resultado |
| --- | --- | --- |
| GET | /orders/{order_id} | Resumen de la orden en español, con total y descuento |
| POST | /orders/{order_id}/confirm | Sin cuerpo. Responde: Orden confirmada. |
| POST | /orders/{order_id}/ship | tracking_number (número de guía). Responde: Orden enviada. |
| POST | /orders/{order_id}/cancel | reason (motivo). Responde: Orden cancelada. |
| POST | /orders/{order_id}/deliver | Responde: Orden entregada. |
| POST | /orders/{order_id}/return | Responde: Devolución de la orden registrada. |
| POST | /orders/{order_id}/items | sku (código) y quantity (cantidad). Responde: Producto agregado a la orden. |

404 identifica una orden o un producto inexistente; 409 indica una operación no permitida en el estado actual; 422 indica datos o una condición de la orden inválidos. Los cuerpos rechazan campos adicionales y cantidades que no sean enteros positivos. Los errores explican el problema sin mostrar nombres de excepciones, estados en inglés ni detalles internos.

Swagger conserva sus secciones de solicitud, código HTTP y cabeceras. El mensaje destinado al cliente se encuentra en **Server response → Response body**.

## Ejemplo en Swagger

1. En POST /orders/{order_id}/confirm, pulsa Try it out y escribe O013 (letra O). Execute devuelve 200 y el texto `Orden confirmada.`.
2. Ejecuta otra vez la misma orden: devuelve 409 y `La orden ya está confirmada. No se puede confirmar otra vez.`. Conserva un solo evento internamente.
3. Usa O007: devuelve 422 y `No se puede confirmar una orden vacía. Agrega al menos un producto.`.
4. Usa O003: devuelve 422 y explica que el cliente está inactivo.
5. Usa NOEXISTE: devuelve 404 y `Orden no existe.`.
6. Confirma O012 y después intenta enviarla con `{"tracking_number":""}`: devuelve 422 y `Escribe el número de guía para poder enviar la orden.`.
7. Consulta O001 u O006 con GET para comprobar los descuentos del 10% y 5%, respectivamente. Los totales se presentan con etiquetas en español.
8. Reinicia el servidor para repetir los casos desde el estado inicial. Recargar Swagger no restablece las órdenes. Las pruebas automáticas crean una aplicación independiente por caso.

Para descargar esta actualización en una copia ya clonada, detén el servidor con Ctrl+C y ejecuta:

```bash
git pull --ff-only
python -m uvicorn app.api:app --reload
```

Después recarga http://127.0.0.1:8000/docs. No necesitas reinstalar paquetes ni volver a crear el entorno.

## Evidencias y diagrama

`evidencias/carga.txt`, `pytest.txt` y `escenarios.txt` conservan la salida real de ejecución. Sus capturas se muestran en visores locales; los HTML identifican expresamente el comando y el archivo de origen. Las imágenes swagger_200, swagger_404, swagger_409 y swagger_422 son capturas reales de /docs de la entrega original, anteriores al ajuste a mensajes en texto. `evidencias/openapi.json` documenta el contrato actualizado.

El archivo `diagramas/techstore_estados.drawio` es editable en https://app.diagrams.net. Su PNG se exportó desde draw.io e incluye una copia editable del diagrama. Los recortes del reporte solo encuadran los resultados; las capturas completas se conservan en el repositorio.




