# 0004 Id por petición y log JSON sin datos personales

Estado: propuesto (sesión 2)

## Contexto

Soporte necesita responder "qué pasó con la petición X". Sin un id común no se pueden unir
la respuesta que vio la persona, el log del servidor y las trazas. El log no debe contener
datos personales (preguntas y respuestas mencionan empleados) y las pruebas deben ser
deterministas.

## Decisión

- Un middleware de FastAPI asigna el id: usa `X-Request-ID` del cliente si cumple
  `^[A-Za-z0-9._-]{1,128}$`; si no, genera un UUID. Lo devuelve en el encabezado de toda
  respuesta y en el cuerpo de `POST /ask` y de los `500`.
- `JsonLogger` escribe una línea JSON por evento en la salida estándar con `ts`, `service`,
  `event` y `request_id`. Eventos: `request`, `agent_run` (solo conteos), `audit` (una por
  herramienta) y `error` (solo el tipo de excepción).
- La hora viene de un `Clock` inyectado (`now()` en UTC para `ts`, `monotonic()` para la
  latencia). Solo `SystemClock` toca el sistema.

## Consecuencias

- Cualquier línea del log se puede filtrar por `request_id`; la página lo muestra para que la
  persona lo pase a soporte.
- El log nunca tiene el texto de preguntas ni respuestas; investigar el contenido requiere
  trazas (ADR 0006), que lo ocultan por omisión.
- Un id del cliente mal formado se reemplaza en silencio: el cliente debe leer el id devuelto.
- Las pruebas inyectan `FixedClock` y un `StringIO` y comparan líneas exactas.
