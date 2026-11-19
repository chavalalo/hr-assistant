# HR Assistant

Asistente que responde preguntas del personal de Recursos Humanos sobre empleados
(por id, como `EMP-0004`, o por departamento) y sobre las políticas de RH
(vacaciones, home office...). Es una API FastAPI sin estado con una página web: el
historial de la conversación vive en el navegador.

Es un sistema multi-agente. Cada `POST /ask` pasa, en orden, por:

1. `guard` (en código): bloquea prompt injection y oculta datos personales.
2. `supervisor`: elige el especialista con reglas en código (`rule:employee`,
   `rule:department`, `rule:policy`) o, si ninguna aplica, con una llamada a
   `MODEL_SMALL` (`model`; una respuesta inválida da `model_invalid` y `directory`).
3. Un especialista con su bucle con tope (`AGENT_MAX_STEPS`): `directory`
   (`get_employee`, `search_by_department`) o `policy` (`search_policy` sobre
   `data/policies.json`).
4. `reviewer` (en código): oculta datos personales de la respuesta, bloquea ids
   inventados y recorta a `MAX_ANSWER_CHARS`.

Cada petición se puede rastrear: lleva un id (`X-Request-ID`), deja líneas JSON en la
salida estándar y se cuenta en `GET /metrics`, que alimenta el tablero
`GET /dashboard`. Opcionalmente, cada agente queda como un run en LangSmith.

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
con `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`, `HIDE_INPUTS=true`,
`HIDE_OUTPUTS=true` y `ANSWER_CACHE_TTL_SECONDS=300` (caché de respuestas de 5
minutos). El health check de Render es `GET /ready`: no manda tráfico a una instancia
a la que le falte el directorio, las políticas o los precios.

Estas variables se escriben en Render (`sync: false`), nunca en el repositorio:

- `API_KEYS`: clientes y claves (`cliente:clave`, 16 caracteres o más por clave).
- `CF_ACCOUNT_ID` y `CF_API_TOKEN`: cuenta y token de Cloudflare.
- `METRICS_CLIENTS`: obligatoria en producción. Clientes que pueden leer
  `GET /metrics`, separados por coma; cada nombre debe ser un cliente de `API_KEYS`.
  Si queda vacía o nombra un cliente que no existe, el producto no arranca
  (compliance).

Son opcionales y no vienen en el Blueprint; si se usan, se agregan a mano en
Render > Environment:

- `CF_AIG_TOKEN`: token de AI Gateway autenticado (secreto).

**Trazas en Render.** El Blueprint no trae ninguna variable de LangSmith y
`LANGSMITH_TRACING` vale `false` por omisión: poner solo la clave no manda ninguna
traza. Para tener trazas hay que agregar a mano en Render > Environment:

- `LANGSMITH_API_KEY`: clave de LangSmith (secreto).
- `LANGSMITH_TRACING=true`: sin ella no se traza, aunque exista la clave.
- `LANGSMITH_PROJECT` (opcional), por ejemplo `hr-assistant`; sin ella las trazas
  van al proyecto `default`.
- `LANGSMITH_ENDPOINT`, solo para cuentas de la región de Europa:
  `https://eu.api.smith.langchain.com`.

`HIDE_INPUTS` y `HIDE_OUTPUTS` deben seguir en `true` (así vienen en el Blueprint):
con `ENVIRONMENT=production` y `LANGSMITH_TRACING=true`, si alguna vale `false` el
producto no arranca (compliance). Los cambios de variables se aplican cuando Render
vuelve a desplegar el servicio.

Render publica solo si el pipeline de CI pasa. La operación del servicio (tablero,
prueba de carga, reporte de costo) está en [doc/operations.md](doc/operations.md); el
modelo de amenazas y los controles, en [doc/security.md](doc/security.md); la
evidencia de costo, en [doc/costs.md](doc/costs.md).

Para comprobar el servicio publicado (la clave se escribe sin que se vea y no
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

Cinco palancas bajan el costo; cada una se mide con `verification evaluate` (la caché
de respuestas, apagada contra encendida):

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

5. **Caché de respuestas** (`ANSWER_CACHE_TTL_SECONDS` > 0, `app/cache.py`): una
   pregunta sin historial y sin datos personales cuya forma normalizada (minúsculas,
   sin acentos, espacios colapsados) ya se respondió dentro del TTL sale de la memoria
   del proceso, sin llamar a ningún modelo: `cached: true`, `cost_usd: 0`, `steps: 0`,
   tokens en 0, `tools_used: []` y `agents: ["guard", "cache"]`, con la misma
   `answer`, `specialist`, `supervisor_route`, `model` y `route` de la primera vez.
   Solo se guardan respuestas completas (`stopped: answer`), sin bloqueo del revisor y
   sin respaldo. Caben `ANSWER_CACHE_MAX_ENTRIES` (sale la más vieja); un candado la
   hace segura con peticiones concurrentes. Es compartida entre clientes porque los
   datos son de solo lectura e iguales para todos. Los aciertos también escriben
   `agent_run` y cuentan en `cache` de `GET /metrics` (`hits`, `misses`, `hit_rate`).

### Resiliencia

- **Reintentos** (`app/resilience.py`): el modelo `gateway` reintenta hasta
  `MODEL_RETRIES` veces ante timeout, `429` o `5xx` (nunca ante otro `4xx`), con espera
  exponencial `MODEL_RETRY_BACKOFF_SECONDS * 2**i` (0.5 s y 1 s por omisión). La
  espera la da el reloj inyectado: en las pruebas no se duerme.
- **Respaldo** (`MODEL_FALLBACK=true`): si el modelo elegido sigue sin responder, el
  especialista se repite una sola vez con el otro (`MODEL_SMALL` <-> `MODEL_LARGE`);
  la respuesta trae `fallback: true` y en `model` el que contestó, y suma en
  `fallbacks` de `GET /metrics`. Si también falla, `502`. Estas respuestas no entran
  a la caché.
- **Sin red** (`FAKE_UNAVAILABLE_MODELS`, solo con `MODEL_PROVIDER=fake`): los modelos
  simulados nombrados fallan como el gateway, sin reintentos, para probar el
  respaldo y el `502`.

El costo se calcula con `data/model_prices.json` (USD por millón de tokens), copia de
`spec/model_prices.json`, que viene de la página de precios de Workers AI. Los precios
cambian: para actualizarlos se edita `spec/model_prices.json` y se vuelve a copiar.
`MODEL_SMALL` y `MODEL_LARGE` deben tener precio o la aplicación no arranca. Con el
modelo simulado hay dos modelos con esos mismos nombres: responden igual, pero cada uno
se cobra con su precio, así que las palancas se miden sin red.

Abre `http://127.0.0.1:8000/`. Cada respuesta muestra su `Id de la petición`, que es
el dato que hay que pasar a soporte. El tablero está en
`http://127.0.0.1:8000/dashboard`.

## Rutas

| Ruta | Clave | Para qué |
| --- | --- | --- |
| `GET /` | no | Página web |
| `GET /dashboard` | no | Tablero de métricas; el HTML no trae datos ni clave (ver «Tablero») |
| `GET /health` | no | `{"status": "ok", "pid": ...}`; solo dice que el proceso vive |
| `GET /ready` | no | `200 {"status": "ready", "checks": {"directory": "ok", "policies": "ok", "prices": "ok"}}`; si un dato falla, `503` con `"status": "not_ready"` y `"error"` en ese check |
| `GET /docs` | no | Documentación de la API |
| `POST /ask` | sí | Recibe `{"question", "history"}`; ver «Respuesta de `POST /ask`» |
| `GET /metrics` | sí | Métricas de este proceso; ver «Métricas»; `403 {"detail": "forbidden"}` si `METRICS_CLIENTS` no nombra al cliente |

### Respuesta de `POST /ask`

| Campo | Qué es |
| --- | --- |
| `answer` | Respuesta en español, ya revisada |
| `steps`, `tools_used` | Vueltas y herramientas del especialista |
| `input_tokens`, `output_tokens` | Tokens del supervisor y del especialista |
| `request_id` | Id de la petición, para soporte |
| `model`, `route` | Modelo que contestó y motivo del enrutador de costo |
| `cached_calls` | Llamadas que AI Gateway respondió desde su caché |
| `cost_usd` | Costo del supervisor más el especialista |
| `specialist` | `directory` o `policy` |
| `agents` | Agentes que corrieron, en orden, por ejemplo `["guard", "supervisor", "directory", "reviewer"]` (`["guard", "cache"]` en un acierto de caché) |
| `supervisor_route` | `rule:employee`, `rule:department`, `rule:policy`, `model` o `model_invalid` |
| `pii_redacted` | Tipos de dato personal ocultados en la entrada o la salida, sin repetir y en orden alfabético |
| `cached` | `true` si salió de la caché de respuestas |
| `fallback` | `true` si respondió el modelo de respaldo |

Errores: `401` sin clave válida, `429` sobre el límite, `422` cuerpo inválido, `400`
si el guardián bloquea la entrada (en ese orden) y `502` si ningún modelo contesta.

### Métricas

`GET /metrics` responde, de este proceso (se pierden al reiniciar):

| Clave | Qué es |
| --- | --- |
| `pid` | Id del proceso |
| `requests`, `error_rate` | Peticiones HTTP y fracción con `5xx` |
| `latency_ms` | `p50` y `p95` (rango más cercano, últimas 1000 peticiones) |
| `tokens` | `input` y `output` acumulados |
| `slo` | `p95_ms_target` (`SLO_P95_MS`) y `met` (`p95` por debajo de la meta) |
| `cost_usd` | Costo acumulado en USD |
| `by_specialist` | Por especialista: `requests` (respuestas `200`, también de caché) y `cost_usd` |
| `by_client` | Por cliente: `requests` y `cost_usd`, igual que arriba |
| `security` | `blocked_inputs`, `pii_redactions` (valores ocultados), `output_blocked` y `access_denied` |
| `cache` | `hits`, `misses` y `hit_rate` = hits / (hits + misses), `0.0` sin consultas |
| `fallbacks` | Respuestas del modelo de respaldo |
| `supervisor` | Cuántas veces decidió una regla (`rule`) y cuántas el modelo (`model`; incluye `model_invalid`); los aciertos de caché no cuentan |

Todos los contadores se suman bajo un candado: son seguros con peticiones
concurrentes. Con varios workers cada proceso tendría los suyos; por eso se corre con
uno solo.

### Tablero

`GET /dashboard` es HTML estático: no trae datos ni clave. Pide la clave en
`data-testid="dashboard-key"` (tipo contraseña) y la guarda en `sessionStorage` con
la misma llave que la página principal (si ya la escribiste ahí, no la vuelve a
pedir). Lee `GET /metrics` al pulsar Enter o al salir del campo, y luego cada 10
segundos. Muestra peticiones (`dashboard-requests`), tasa de error
(`dashboard-error-rate`), p50 y p95 contra el SLO (`dashboard-p95`), costo total y
por respuesta (`dashboard-cost`), tasa de aciertos de la caché
(`dashboard-cache-hit-rate`), supervisor y respaldo, tabla por especialista
(`dashboard-specialists`), tabla por cliente (`dashboard-clients`) y contadores de
seguridad (`dashboard-security`). Con `401` muestra «Clave inválida» y con `403`
«Sin permiso para ver métricas». Solo usa `textContent`, nunca `innerHTML`.

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
  modelo simulado, sin clientes, con una clave de menos de 16 caracteres, con trazas
  pedidas sin `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`, o con `METRICS_CLIENTS` vacía
  o con un cliente que no está en `API_KEYS`. La lista de reglas, dónde están y cómo
  se comprueban está en `doc/compliance-checklist.md`.
- **Guardián de entrada** (`app/guard.py`, en código, antes de cualquier modelo). Si
  la pregunta o un mensaje `user` del historial pide ignorar u olvidar instrucciones,
  revelar el prompt del sistema o cambiar de rol («ignora las instrucciones», «ignore
  previous instructions», «revela tu prompt», «system prompt», «actúa como», «modo
  desarrollador», «jailbreak», sin importar acentos ni mayúsculas), `POST /ask`
  responde `400 {"detail": "request blocked by input policy", "request_id": ...}`.
  Los mensajes `assistant` no bloquean. Orden de rechazos: `401`, `429`, `422`, `400`.
- **Datos personales** (`app/pii.py`). Correo, teléfono de 10 dígitos (con o sin
  `+52`), CURP, RFC, tarjeta de 13 a 19 dígitos que pasa Luhn y NSS de 11 dígitos se
  reemplazan por `[EMAIL]`, `[PHONE]`, `[CURP]`, `[RFC]`, `[CARD]` y `[NSS]` en la
  pregunta y el historial (antes del modelo, el log y la traza) y en la respuesta. Los
  tipos ocultados salen en `pii_redacted`. Los ids `EMP-dddd` nunca son PII.
- **Revisor de salida** (`app/reviewer.py`). Oculta la PII de la respuesta; si cita un
  id `EMP-dddd` que no existe en el directorio **y que la persona no escribió en su
  pregunta** (un id inventado por el modelo), la reemplaza por «No pude verificar la
  respuesta con el directorio. Intenta de nuevo.»; al final la recorta a
  `MAX_ANSWER_CHARS`. Si la persona preguntó por un id que no existe, la respuesta
  puede decirlo («EMP-0099 no existe»). Los ids se comparan sin distinguir
  mayúsculas, contra la pregunta ya redactada por el guardián.
- **Mínimo privilegio.** Con `METRICS_CLIENTS` con valor, solo esos clientes leen
  `GET /metrics`; otro cliente con clave válida recibe `403 {"detail": "forbidden"}`.
  Vacía, todos los clientes pueden leerlas (solo para desarrollo).
- **Auditoría.** Líneas `audit` con `client` y `action`: `tool_call`, `input_blocked`
  (`reason: prompt_injection`), `pii_redacted` (`location`: `input` u `output`,
  `types` y `count`), `output_blocked` (`reason: unknown_employee_id`),
  `access_denied` (`path`) y `metrics_read`. Nunca el texto de la pregunta, de la
  respuesta ni el valor de un dato personal.
- **AI Gateway autenticado.** Si `CF_AIG_TOKEN` tiene valor, cada llamada al gateway
  manda `cf-aig-authorization: Bearer <token>`. El token no sale en `repr`, el log, la
  traza ni un error.
- **Página.** La clave se escribe en el campo «Clave de acceso» (tipo contraseña), se
  guarda solo en `sessionStorage` (se borra al cerrar la pestaña) y se manda en
  `X-API-Key`. Con `401` la página muestra «Clave inválida»; con `429`, «Demasiadas
  preguntas; espera N segundos»; con `400`, que la pregunta fue bloqueada. Cada
  respuesta del asistente lleva `data-testid="assistant-answer"`.
- La clave nunca se escribe en el log, en la traza ni en un mensaje de error: solo el
  nombre del cliente.

Toda respuesta trae el encabezado `X-Request-ID`. Si el cliente lo manda y es válido
(letras, dígitos, `.`, `_` o `-`, hasta 128 caracteres) se conserva; si no, se genera
un UUID. Un error inesperado responde `500` con
`{"detail": "internal error", "request_id": ...}`.

## Log

Una línea JSON por evento en la salida estándar, con `ts` (UTC, del reloj inyectado),
`service`, `event` y `request_id`. Eventos:

| Evento | Campos |
| --- | --- |
| `request` | `client` (o `null` en rutas públicas y rechazos), `method`, `path`, `status`, `latency_ms` |
| `agent_run` | `client`, `question_chars`, `history_messages`, `steps`, `tools`, `input_tokens`, `output_tokens`, `stopped`, `model`, `route`, `history_sent`, `cached_calls`, `cost_usd`, `specialist`, `agents`, `supervisor_route`, `pii_types`, `cached`, `fallback`; también en los aciertos de caché |
| `audit` | `client` y `action` (`tool_call` con `tool` y `args`, `input_blocked`, `pii_redacted`, `output_blocked`, `access_denied`, `metrics_read`; ver «Seguridad») |
| `auth_rejected` | `reason`: `missing` o `invalid` |
| `rate_limited` | `client` y `retry_after` |
| `error` | Solo el tipo de error, por ejemplo `ModelUnavailable` |

Nunca el texto de la pregunta ni de la respuesta, ni el valor de un dato personal.

## Trazas

Con `LANGSMITH_TRACING=true` y `LANGSMITH_API_KEY`, cada `POST /ask` deja un run raíz
`request` y, dentro, un run por agente: `agent.guard`, `agent.supervisor`,
`agent.directory` o `agent.policy` (con sus llamadas `model.complete` y herramientas)
y `agent.reviewer`. Todos llevan `request_id` y `client` en los metadatos; desde que
el supervisor decide, también `specialist` (la salida de `agent.supervisor` dice cuál
eligió). El run raíz, `agent.guard`, `agent.supervisor` y `agent.reviewer` no tienen
entradas y su salida es un resumen (tipos, conteos, decisiones y costo): la pregunta
original nunca llega a la traza. El especialista recibe solo texto ya redactado, y con
`HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` (por omisión) no se manda texto. Sin la
clave no se importa `langsmith` ni se abre ninguna conexión; en las pruebas el tracer
se inyecta.

Hacen falta las dos: `LANGSMITH_TRACING` vale `false` por omisión, así que con solo
`LANGSMITH_API_KEY` no se traza nada (y sin la clave tampoco, aunque
`LANGSMITH_TRACING=true`). Dos variables más las lee directamente la librería
`langsmith` del entorno, no `app/config.py`:

- `LANGSMITH_PROJECT` (opcional), por ejemplo `hr-assistant`; sin ella las trazas
  van al proyecto `default`.
- `LANGSMITH_ENDPOINT`, solo para cuentas de la región de Europa:
  `https://eu.api.smith.langchain.com`; sin ella se usa el endpoint de Estados
  Unidos y las trazas no aparecen en una cuenta europea.

`HIDE_INPUTS` y `HIDE_OUTPUTS` deben quedar en `true`: con `ENVIRONMENT=production`
y `LANGSMITH_TRACING=true`, si alguna vale `false` el producto no arranca
(compliance). En Render estas variables se agregan a mano; ver «Publicar en Render».

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
| `LANGSMITH_PROJECT` | `default` | Proyecto de LangSmith, opcional (la lee `langsmith`, no la app) |
| `LANGSMITH_ENDPOINT` | endpoint de EE. UU. | Solo cuentas de Europa: `https://eu.api.smith.langchain.com` (la lee `langsmith`) |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | No mandar a LangSmith el texto de preguntas ni respuestas |
| `CF_ACCOUNT_ID` | vacía | Cuenta de Cloudflare (obligatoria con `gateway`) |
| `CF_GATEWAY_ID` | `default` | Gateway de AI Gateway (obligatorio con `gateway`) |
| `CF_API_TOKEN` | vacía | Token de Cloudflare, secreto (obligatorio con `gateway`) |
| `CF_AIG_TOKEN` | vacía | Token de AI Gateway autenticado, secreto y opcional; va en `cf-aig-authorization` |
| `METRICS_CLIENTS` | vacía | Clientes de `API_KEYS` que leen `GET /metrics`; vacía: todos; obligatoria en `production` |
| `MAX_ANSWER_CHARS` | `1500` | Largo máximo de la respuesta (entero mayor que 0) |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | Modelo barato |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Modelo capaz |
| `ROUTING` | `true` | Enrutamiento por pregunta (`true` o `false`) |
| `ROUTER_MAX_CHARS` | `80` | Preguntas más largas van al modelo capaz (entero mayor que 0) |
| `HISTORY_WINDOW` | `6` | Mensajes de historial que se mandan (entero, 0 o más) |
| `MODEL_MAX_TOKENS` | `300` | Tope de tokens de salida (entero mayor que 0) |
| `MODEL_TEMPERATURE` | `0` | Temperatura; con 0 las evaluaciones son repetibles |
| `CACHE_TTL_SECONDS` | `0` | Caché del gateway en segundos (0: apagada) |
| `PRICES_PATH` | `data/model_prices.json` | Precios por modelo, relativo a `product/` |
| `MODEL_RETRIES` | `2` | Reintentos del gateway ante timeout, `429` o `5xx` (entero, 0 o más) |
| `MODEL_RETRY_BACKOFF_SECONDS` | `0.5` | Primera espera entre reintentos; se duplica (número, 0 o más) |
| `MODEL_FALLBACK` | `true` | Repetir el especialista una vez con el otro modelo (`true` o `false`) |
| `FAKE_UNAVAILABLE_MODELS` | vacía | Modelos simulados que fallan, separados por coma; solo con `fake` |
| `ANSWER_CACHE_TTL_SECONDS` | `0` | Vida de la caché de respuestas en segundos (0: apagada) |
| `ANSWER_CACHE_MAX_ENTRIES` | `256` | Tope de entradas de la caché de respuestas (entero mayor que 0) |
| `POLICIES_PATH` | `data/policies.json` | Políticas de RH, relativo a `product/` (copia de `spec/policies.json`) |

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
uv run python -m verification load      # 60 peticiones con 10 hilos, todas 200
```

Las pruebas usan un reloj fijo, el log en memoria y trazas apagadas: no usan red. El
modelo de gateway se prueba con un cliente `httpx` inyectado (`MockTransport`).
