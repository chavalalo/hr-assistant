# HR Assistant

Asistente que responde preguntas del personal de Recursos Humanos sobre empleados
(por id, como `EMP-0004`, o por departamento). Es una API FastAPI sin estado con una
página web: el historial de la conversación vive en el navegador y un solo agente, con
un bucle con tope, consulta un directorio de empleados de solo lectura.

Cada petición se puede rastrear: lleva un id (`X-Request-ID`), deja líneas JSON en la
salida estándar y se cuenta en `GET /metrics`. Opcionalmente, las corridas del agente
quedan como trazas en LangSmith.

Cada respuesta dice qué modelo la contestó y cuánto costó. Por omisión el modelo es
simulado (sin red y sin gastar cuota); con `MODEL_PROVIDER=gateway` usa Cloudflare
Workers AI a través de AI Gateway.

La arquitectura y las decisiones están en `doc/architecture.md` y `doc/adr/`.

## Cómo correrlo

Desde la carpeta `product/`:

```bash
uv pip install -r requirements.txt
cp .env.example .env   # pon al menos un cliente en API_KEYS
uv run uvicorn app.main:app --reload
```

Sin `API_KEYS` el producto arranca, pero `POST /ask` y `GET /metrics` responden `401`
a todos: es el comportamiento seguro por omisión. Inventa una clave larga para tu
cliente, ponla en `.env` y escríbela en el campo «Clave de acceso» de la página.

Para el modelo real pon `MODEL_PROVIDER=gateway` y llena `CF_ACCOUNT_ID`,
`CF_GATEWAY_ID` y `CF_API_TOKEN` (sin las tres no arranca). El token es secreto: va
solo en `.env`, nunca en el repositorio, y no aparece en el log ni en los errores.

### Con Docker

```bash
docker build -t hr-assistant .
docker run --rm -p 8000:8000 --env-file .env hr-assistant
```

La imagen usa `python:3.12-slim`, corre con un usuario que no es root y escucha en
`${PORT:-8000}`. `.env` no entra en la imagen: las variables se pasan al correrla.

### Publicar en Render

Una persona aprueba la publicación; después `scripts/publish.py` (en la raíz de la
fábrica) crea el repositorio en GitHub y hace el push. `render.yaml` es un Blueprint
con `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`, `HIDE_INPUTS=true` y
`HIDE_OUTPUTS=true`; `API_KEYS`, `CF_ACCOUNT_ID` y `CF_API_TOKEN` se escriben en Render
(`sync: false`), nunca en el repositorio. Render publica solo si el pipeline de CI
pasa. Para comprobar el servicio publicado (la clave se escribe sin que se vea y no
queda en el historial de la terminal):

```bash
read -rs SMOKE_API_KEY && export SMOKE_API_KEY
python scripts/smoke.py https://<tu-servicio>.onrender.com
```

## Costo y palancas

El modelo real recibe
`POST https://gateway.ai.cloudflare.com/v1/{CF_ACCOUNT_ID}/{CF_GATEWAY_ID}/workers-ai/v1/chat/completions`
con `Authorization: Bearer {CF_API_TOKEN}`. Si falla, `POST /ask` responde `502` con
`{"detail": "model unavailable", "request_id": ...}`.

Cuatro palancas bajan el costo; cada una se mide con `verification evaluate`:

1. **Enrutamiento** (`ROUTING`, `ROUTER_MAX_CHARS`): una regla en código manda al
   modelo capaz (`MODEL_LARGE`) las preguntas largas o con «compara», «resume»,
   «explica», «por qué», «analiza» o «todos» (sin importar acentos ni mayúsculas); el
   resto va al barato (`MODEL_SMALL`). El motivo sale en `route`: `routing_off`,
   `long_question`, `keyword:<palabra>` o `simple`.
2. **Ventana de historial** (`HISTORY_WINDOW`): solo se mandan los últimos mensajes.
3. **Tope de salida** (`MODEL_MAX_TOKENS`) en cada llamada.
4. **Caché de AI Gateway** (`CACHE_TTL_SECONDS` > 0): manda `cf-aig-cache-ttl`; si el
   gateway responde `cf-aig-cache-status: HIT`, esa llamada cuenta en `cached_calls` y
   no cuesta.

El costo se calcula con `data/model_prices.json` (USD por millón de tokens), copia de
`spec/model_prices.json`, que viene de la página de precios de Workers AI. Los precios
cambian: para actualizarlos se edita `spec/model_prices.json` y se vuelve a copiar.
`MODEL_SMALL` y `MODEL_LARGE` deben tener precio o la aplicación no arranca. Con el
modelo simulado hay dos modelos con esos mismos nombres: responden igual, pero cada uno
se cobra con su precio, así que las palancas se miden sin red.

Abre `http://127.0.0.1:8000/`. Cada respuesta muestra su `Id de la petición`, que es
el dato que hay que pasar a soporte.

## Rutas

| Ruta | Clave | Para qué |
| --- | --- | --- |
| `GET /` | no | Página web |
| `GET /health` | no | `{"status": "ok", "pid": ...}` |
| `GET /docs` | no | Documentación de la API |
| `POST /ask` | sí | Recibe `{"question", "history"}` y responde `answer`, `steps`, `tools_used`, `input_tokens`, `output_tokens`, `request_id`, `model`, `route`, `cached_calls` y `cost_usd` |
| `GET /metrics` | sí | `pid`, `requests`, `error_rate`, `latency_ms` (`p50`, `p95`), `tokens`, `slo` y `cost_usd` acumulado de este proceso |

## Seguridad

- **Clave por cliente.** `API_KEYS` tiene la forma `cliente:clave,cliente2:clave2`.
  Las rutas con clave piden el encabezado `X-API-Key`; sin clave o con una inválida
  responden `401 {"detail": "invalid or missing API key"}`. Las claves se comparan con
  `hmac.compare_digest` contra todas, en tiempo constante. Si `API_KEYS` está mal
  formada, el producto no arranca y el error dice qué entrada falla y su largo, nunca
  su valor.
- **Límite por cliente.** Más de `RATE_LIMIT_PER_MINUTE` peticiones en una ventana
  deslizante de 60 segundos responden `429 {"detail": "rate limit exceeded"}` con
  `Retry-After` (segundos que faltan). Primero se revisa la clave y después el límite;
  las peticiones rechazadas no cuentan. El límite vive en la memoria del proceso: con
  varios workers se multiplica, por eso se corre con uno solo.
- **Compliance.** Con `ENVIRONMENT=production` el producto se niega a arrancar con el
  modelo simulado, sin clientes, con una clave de menos de 16 caracteres o con trazas
  pedidas sin `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`. La lista de reglas, dónde
  están y cómo se comprueban está en `doc/compliance-checklist.md`.
- **Página.** La clave se escribe en el campo «Clave de acceso» (tipo contraseña), se
  guarda solo en `sessionStorage` (se borra al cerrar la pestaña) y se manda en
  `X-API-Key`. Con `401` la página muestra «Clave inválida»; con `429`, «Demasiadas
  preguntas; espera N segundos».
- La clave nunca se escribe en el log, en la traza ni en un mensaje de error: solo el
  nombre del cliente.

Toda respuesta trae el encabezado `X-Request-ID`. Si el cliente lo manda y es válido
(letras, dígitos, `.`, `_` o `-`, hasta 128 caracteres) se conserva; si no, se genera
un UUID. Un error inesperado responde `500` con
`{"detail": "internal error", "request_id": ...}`.

## Log

Una línea JSON por evento en la salida estándar, con `ts` (UTC), `service`, `event` y
`request_id`. Eventos: `request` (con `client`, o `null` en rutas públicas y
rechazos), `agent_run` (`client`, conteos, `model`, `route`, `history_sent`,
`cached_calls` y `cost_usd`; nunca el texto de la pregunta ni de la respuesta), `audit`
(una por herramienta llamada, con `client`), `auth_rejected` (`reason`: `missing` o
`invalid`), `rate_limited` (`client` y `retry_after`) y `error` (solo el tipo de error,
por ejemplo `ModelUnavailable`). Las trazas de LangSmith llevan `request_id` y `client`
en sus metadatos.

## Variables de entorno

| Variable | Por omisión | Para qué |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | vacía | Clientes y claves, `cliente:clave,cliente2:clave2` (secreto) |
| `RATE_LIMIT_PER_MINUTE` | `30` | Peticiones por cliente por minuto (entero mayor que 0) |
| `MODEL_PROVIDER` | `fake` | Modelo de lenguaje: `fake` (simulado) o `gateway` |
| `AGENT_MAX_STEPS` | `3` | Tope de vueltas del agente (entero mayor que 0) |
| `MAX_QUESTION_CHARS` | `2000` | Largo máximo de la pregunta (entero mayor que 0) |
| `EMPLOYEES_PATH` | `data/employees.json` | Archivo de empleados, relativo a `product/` |
| `SERVICE_NAME` | `hr-assistant` | Campo `service` del log |
| `SLO_P95_MS` | `2000` | Meta de latencia p95 en milisegundos (entero mayor que 0) |
| `LANGSMITH_TRACING` | `false` | Enciende las trazas en LangSmith (`true` o `false`) |
| `LANGSMITH_API_KEY` | sin valor | Clave de LangSmith; sin ella no se traza ni se intenta conectar |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith el texto de preguntas ni respuestas |
| `CF_ACCOUNT_ID` | vacía | Cuenta de Cloudflare (obligatoria con `gateway`) |
| `CF_GATEWAY_ID` | `default` | Gateway de AI Gateway (obligatorio con `gateway`) |
| `CF_API_TOKEN` | vacía | Token de Cloudflare, secreto (obligatorio con `gateway`) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta (`true` o `false`) |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz (entero mayor que 0) |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (entero, 0 o más) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida (entero mayor que 0) |
| `MODEL_TEMPERATURE` | `0` | Temperatura; con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo, relativo a `product/` |

`.env.example` trae todas las variables sin valores secretos. Un valor inválido impide
arrancar con un `ConfigError`. La clave de LangSmith se lee del entorno y nunca se
guarda en la configuración ni se escribe en el log; el token de Cloudflare y las claves
de `API_KEYS` se guardan pero no salen en `repr` ni en ningún mensaje.

## Pruebas

Desde la raíz del repositorio:

```bash
uv run python -m verification unit   # pruebas del producto, cobertura de 80 % o más
uv run python -m verification qa     # estilo de QA.md (pylint, 88 columnas, sin emojis)
uv run python -m verification contract  # contratos contra el producto corriendo
uv run python -m verification e2e       # Playwright sobre la página (modelo simulado)
uv run python -m verification evaluate  # costo y calidad: línea base contra palancas
```

Las pruebas usan un reloj fijo, el log en memoria y trazas apagadas: no usan red. El
modelo de gateway se prueba con un cliente `httpx` inyectado (`MockTransport`).
