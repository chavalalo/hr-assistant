# Operación del HR Assistant

Cómo desplegar en Render, qué variables escribir, qué corre la CI, cómo comprobar el servicio
publicado (humo y carga), dónde mirar (tablero, `/metrics`, LangSmith) y qué hacer ante los
errores más comunes.

Ver también: [arquitectura](architecture.md), [seguridad](security.md), [costos](costs.md) y
[lista de compliance](compliance-checklist.md).

## Despliegue en Render

1. Una persona aprueba la publicación (`output/approved.txt`); `scripts/publish.py`, en la raíz
   de la fábrica, crea el repositorio privado en GitHub y hace el push.
2. En Render: New > Blueprint, sobre ese repositorio. `render.yaml` crea el servicio web
   `hr-assistant` (`runtime: docker`, `dockerfilePath: ./Dockerfile`, plan `free`).
3. Render pide el valor de cada variable con `sync: false` (ver la tabla siguiente).
4. `autoDeployTrigger: checksPass`: Render publica un commit solo cuando el pipeline de CI pasa.
5. Al arrancar, `create_app` valida la configuración (`Settings.from_env`) y aplica
   `compliance.enforce`. Si falta `METRICS_CLIENTS` o nombra un cliente que no está en
   `API_KEYS`, el proceso termina con `ConfigError` y el despliegue falla: es a propósito.
6. `healthCheckPath: /ready`: Render manda tráfico solo cuando `/ready` responde `200 {"status":
   "ready", "checks": {"directory": "ok", "policies": "ok", "prices": "ok"}}`. Si un dato falla,
   `/ready` responde `503` con `"not_ready"` y ese check en `"error"`, sin el mensaje interno.
   `/health` (solo dice que el proceso vive) sigue disponible para la prueba de humo.

Valores fijos que pone el Blueprint: `ENVIRONMENT=production`, `MODEL_PROVIDER=gateway`,
`HIDE_INPUTS=true`, `HIDE_OUTPUTS=true` y `ANSWER_CACHE_TTL_SECONDS=300`. El resto toma su valor
por omisión (tabla de configuración en [architecture.md](architecture.md)). En particular,
`LANGSMITH_TRACING` vale `false` por omisión (`app/config.py`) y `render.yaml` no la define: sin
agregarla a mano no hay trazas, aunque exista `LANGSMITH_API_KEY`.

El servicio corre con un solo worker: el límite por cliente, las métricas y la caché de
respuestas viven en la memoria del proceso (ADR 0005 y 0015). Se pierden en cada despliegue o
reinicio, y cuando el plan gratuito duerme el servicio.

### Variables en Render > Environment

Ningún secreto va en el repositorio ni en `render.yaml`.

| Variable | Obligatoria | Qué poner |
| --- | --- | --- |
| `API_KEYS` | sí (`sync: false`) | `cliente:clave,cliente2:clave2`; cada clave de 16 caracteres o más (compliance). Un cliente por consumidor: por ejemplo uno para el portal, uno para operación y uno para la prueba de carga. |
| `CF_ACCOUNT_ID` | sí (`sync: false`) | Id de la cuenta de Cloudflare. |
| `CF_API_TOKEN` | sí (`sync: false`) | Token de Cloudflare con permiso de Workers AI. Secreto. |
| `METRICS_CLIENTS` | sí (`sync: false`) | Nombres de clientes de `API_KEYS` que pueden leer `/metrics` y el tablero, separados por coma (por ejemplo `ops`). Vacía o con un nombre que no está en `API_KEYS`: no arranca. |
| `CF_AIG_TOKEN` | no | Solo si el gateway de AI Gateway es autenticado; va en `cf-aig-authorization`. Secreto. No está en el Blueprint: se agrega a mano. |
| `LANGSMITH_API_KEY` | no (para trazas, sí) | Clave de LangSmith. Secreto. No está en el Blueprint: se agrega a mano. Sola no enciende nada: hace falta también `LANGSMITH_TRACING=true`. |
| `LANGSMITH_TRACING` | no (para trazas, sí) | `true` para encender las trazas. Por omisión `false` y no está en el Blueprint: se agrega a mano. Solo acepta `true` o `false`; otro valor impide arrancar. |
| `LANGSMITH_PROJECT` | no | Nombre del proyecto de LangSmith donde caen las trazas. Sin ella van al proyecto `default`. La lee la librería `langsmith` del entorno. |
| `LANGSMITH_ENDPOINT` | no | Solo si la cuenta de LangSmith es de la región de Europa: `https://eu.api.smith.langchain.com`. Sin ella se usa la región de Estados Unidos. La lee la librería `langsmith` del entorno. |

`CF_GATEWAY_ID` vale `default` si no se escribe; si el gateway tiene otro nombre, se agrega
también. Cambiar una variable en Render reinicia el servicio.

## CI (`.github/workflows/ci.yml`)

Cuatro trabajos encadenados (`needs`); si uno falla los siguientes no corren y Render no publica.

| Trabajo | Qué hace |
| --- | --- |
| `style` | `pylint app tests scripts` (88 columnas, `--fail-under=10`). |
| `unit` | `pytest tests` con cobertura de `app` de 80 % o más. |
| `e2e` | Arranca el producto con el modelo simulado (`MODEL_PROVIDER=fake`, una clave de ejemplo y `RATE_LIMIT_PER_MINUTE=1000`), corre Playwright (`pytest e2e`), después `python scripts/load_test.py $BASE_URL` y `python scripts/cost_report.py uvicorn.log`. Si algo falla, imprime `uvicorn.log`. |
| `docker` | `docker build` de la imagen. |

## Prueba de humo

Contra el servicio publicado, con una clave de `API_KEYS` (se escribe sin que se vea y no queda
en el historial de la terminal):

```bash
read -rs SMOKE_API_KEY && export SMOKE_API_KEY
python scripts/smoke.py https://<tu-servicio>.onrender.com     # desde product/
uv run python -m verification production https://<tu-servicio>.onrender.com   # desde la raíz
```

Comprobación rápida a mano, sin clave: `GET /health` y `GET /ready` deben responder `200`.

## Prueba de carga

`scripts/load_test.py` manda `--requests` peticiones (60 por omisión) con `--concurrency` hilos
(10 por omisión) a `POST /ask`, alternando preguntas de directorio y de políticas. Lee la clave
solo de `SMOKE_API_KEY` y nunca la imprime. Reporta el conteo por código, `p50_ms`, `p95_ms`,
`rps` y `costo_total_usd`. Termina con 1 si hubo `5xx` o peticiones sin respuesta, con 2 si falta
la clave; los `429` se reportan pero no hacen fallar.

```bash
cd product
read -rs SMOKE_API_KEY && export SMOKE_API_KEY
python scripts/load_test.py https://<tu-servicio>.onrender.com --requests 25 --concurrency 5
```

Antes de correrla contra Render:

- **Límite por minuto.** Con `RATE_LIMIT_PER_MINUTE` en 30 (por omisión), 60 peticiones de un
  mismo cliente dan unos 30 `429`. Usa un cliente dedicado a la carga y, si quieres que todas
  sean `200`, sube el límite de forma temporal en Render > Environment (y bájalo al terminar), o
  manda menos de 30 peticiones por minuto (por ejemplo `--requests 25`, como en la evidencia de
  producción).
- **Cuota y caché.** Con el modelo real cada fallo de caché gasta cuota de Workers AI. Como las
  preguntas se repiten y `ANSWER_CACHE_TTL_SECONDS=300`, casi todas salen de la caché: el
  `costo_total_usd` de la carga no representa el costo de preguntas distintas.
- **Arranque en frío.** El plan gratuito duerme el servicio; la primera petición puede tardar
  hasta un minuto (el script espera 90 s por petición). Haz un `GET /health` antes de medir.

### Evidencia local

`uv run python -m verification load` arranca el producto con el modelo simulado y manda 60
peticiones con 10 hilos; pasa si todas responden `200`:

```text
requests=60 concurrency=10 ok=60 p50_ms=21.0 p95_ms=28.4 rps=445.4
```

60 de 60 respuestas `200`, p50 de 21.0 ms y p95 de 28.4 ms (muy por debajo de `SLO_P95_MS` =
2000), 445.4 peticiones por segundo. Con el modelo simulado no hay red: la latencia real la pone
Workers AI y se mide con `scripts/load_test.py` contra Render.

## Evidencia de producción (2026-11-19)

Contra `https://hr-assistant-1q29.onrender.com`, con el modelo real (`MODEL_PROVIDER=gateway`).

**Prueba de humo.**

| Comprobación | Resultado |
| --- | --- |
| `GET /health` | `200` |
| `POST /ask` sin clave | `401` |
| `POST /ask` con clave | `200` |

**Prueba de carga.** `python scripts/load_test.py https://hr-assistant-1q29.onrender.com
--requests 25 --concurrency 5`:

| Medida | Valor |
| --- | --- |
| Respuestas | 25 de 25 con `200`; ningún `5xx` ni petición sin respuesta |
| `p50_ms` | 139.4 |
| `p95_ms` | 2327.6 |
| `rps` | 5.3 |
| `costo_total_usd` | 0.002542 |

Se usan 25 peticiones para quedar bajo el límite de 30 por minuto por cliente
(`RATE_LIMIT_PER_MINUTE`), así ninguna recibe `429`. La p50 baja viene de la caché de respuestas
(`ANSWER_CACHE_TTL_SECONDS=300`): las cinco preguntas de `load_test.py` se repiten y, después de
la primera vez, salen de la caché. La p95 corresponde a las llamadas reales a Workers AI (fallos
de caché); queda por encima de `SLO_P95_MS` = 2000 en esta medición, con una muestra pequeña.

**Traza en LangSmith.** Un `POST /ask` de directorio dejó el run raíz `request` (0.86 s) con este
árbol:

```text
request
├── agent.guard
├── agent.supervisor
├── agent.directory
│   ├── model.complete
│   ├── search_by_department
│   └── model.complete
└── agent.reviewer
```

Las entradas y salidas se ven como «No inputs» y «No outputs» (`HIDE_INPUTS=true` y
`HIDE_OUTPUTS=true`) y el run lleva los metadatos `client` y `request_id`.

## Reporte de costos

```bash
python scripts/cost_report.py uvicorn.log        # o desde la entrada estándar
```

Resume las líneas `agent_run` por cliente, especialista y modelo, con la tasa de caché. En
Render, descarga o copia los logs del servicio (Logs) a un archivo y pásalo al script. Detalle
de las palancas y la evidencia en [costs.md](costs.md).

## Dónde mirar

### Tablero: `GET /dashboard`

Abre `https://<tu-servicio>.onrender.com/dashboard` y escribe una clave de un cliente de
`METRICS_CLIENTS` en el campo de clave (`dashboard-key`). La clave se guarda en
`sessionStorage` (la misma llave que la página principal) y el tablero lee `/metrics` cada 10 s.
Muestra peticiones, tasa de error, p50 y p95 contra el SLO, costo total y por respuesta, tasa de
aciertos de la caché, supervisor y respaldo, tablas por especialista y por cliente y contadores
de seguridad. Con una clave inválida dice «Clave inválida»; con un cliente fuera de
`METRICS_CLIENTS`, «Sin permiso para ver métricas». El HTML no trae datos ni clave.

### `GET /metrics`

Con `X-API-Key` de un cliente de `METRICS_CLIENTS`. Además de `requests`, `error_rate`,
`latency_ms`, `tokens`, `slo` y `cost_usd`, trae `by_specialist`, `by_client`, `security`
(`blocked_inputs`, `pii_redactions`, `output_blocked`, `access_denied`), `cache` (`hits`,
`misses`, `hit_rate`), `fallbacks` y `supervisor` (`rule`, `model`). Son de este proceso: se
reinician con cada despliegue.

### Log

Una línea JSON por evento en la salida estándar (Render > Logs): `request`, `agent_run`,
`audit`, `auth_rejected`, `rate_limited` y `error`. Todas llevan `request_id`: es el dato que la
persona ve en la página (`Id de la petición`) y pasa a soporte. Nunca llevan el texto de la
pregunta ni de la respuesta.

### LangSmith

Las trazas están apagadas por omisión: `LANGSMITH_TRACING` vale `false` en `app/config.py` y
`render.yaml` no define ninguna variable de LangSmith. El producto traza solo si
`LANGSMITH_TRACING=true` **y** `LANGSMITH_API_KEY` tiene valor; con una sola de las dos no manda
nada y no avisa. Para encenderlas, agrega a mano en Render > Environment:

1. `LANGSMITH_API_KEY`: la clave de LangSmith (secreto).
2. `LANGSMITH_TRACING=true`.
3. `LANGSMITH_PROJECT` (opcional): el proyecto donde quieres ver las trazas. Sin ella van al
   proyecto `default`.
4. `LANGSMITH_ENDPOINT`, solo si la cuenta es de la región de Europa:
   `https://eu.api.smith.langchain.com`. Si la cuenta es de Europa y falta, las trazas no llegan
   a tu cuenta.

`LANGSMITH_PROJECT` y `LANGSMITH_ENDPOINT` no las lee el producto: las toma la librería
`langsmith` del entorno al crear su cliente. `HIDE_INPUTS` y `HIDE_OUTPUTS` deben seguir en
`true` (ya lo están en el Blueprint): con `LANGSMITH_TRACING=true` en producción, compliance no
deja arrancar si alguna vale `false`. Guardar las variables reinicia el servicio; después manda
una pregunta y busca la traza.

Cada `POST /ask` deja un run raíz `request` con `agent.guard`, `agent.supervisor`,
`agent.directory` o `agent.policy` y `agent.reviewer` dentro. Dentro del especialista aparecen
las llamadas al modelo (`model.complete`) y las herramientas (`get_employee`,
`search_by_department` o `search_policy`). Busca por el metadato `request_id`; también llevan
`client` y, desde el supervisor, `specialist`. Ejemplo real en la
[evidencia de producción](#evidencia-de-producción-2026-11-19).

## Qué hacer ante...

| Síntoma | Qué significa | Qué revisar y hacer |
| --- | --- | --- |
| `502 {"detail": "model unavailable"}` | Ningún modelo contestó: el elegido falló tras `MODEL_RETRIES` reintentos (solo timeout, `429` o `5xx`) y el de respaldo también, o el error no era reintentable. | En el log, una línea `error` con `error_type: ModelUnavailable` y el `request_id`. Revisa el estado de Cloudflare y la cuota de Workers AI; que `CF_ACCOUNT_ID`, `CF_GATEWAY_ID` y `CF_API_TOKEN` sean correctos y el token siga vigente; si el gateway es autenticado, que `CF_AIG_TOKEN` exista y sea válido (sin él el gateway rechaza todas las llamadas). `/ready` puede seguir en `200`: no llama al modelo. |
| Muchas respuestas con `fallback: true` | El modelo elegido por el enrutador está caído y contesta el otro (`MODEL_SMALL` <-> `MODEL_LARGE`). | `fallbacks` en `/metrics` y en el tablero; `fallback` y `model` en `agent_run`. Si el que falla es `MODEL_LARGE`, la calidad de las preguntas complejas puede bajar; si es `MODEL_SMALL`, el costo sube. Revisa el modelo en Cloudflare; si la caída es larga, cambia `MODEL_SMALL` o `MODEL_LARGE` por otro modelo con precio en `data/model_prices.json` (requiere commit si el precio no existe). Las respuestas de respaldo no entran a la caché. |
| `429 {"detail": "rate limit exceeded"}` | Ese cliente pasó `RATE_LIMIT_PER_MINUTE` en 60 s. | Línea `rate_limited` con `client` y `retry_after`; el encabezado `Retry-After` dice cuántos segundos esperar. Si el uso es legítimo, sube `RATE_LIMIT_PER_MINUTE` en Render > Environment o da a ese consumidor su propio cliente en `API_KEYS`. Si no, revoca su clave (quítala de `API_KEYS`). |
| `403 {"detail": "forbidden"}` en `/metrics` o «Sin permiso para ver métricas» en el tablero | La clave es válida pero el cliente no está en `METRICS_CLIENTS`. | `audit` `access_denied` con `path` y `client`; contador `security.access_denied`. Si debe ver las métricas, agrega su nombre (no su clave) a `METRICS_CLIENTS` en Render > Environment; el nombre debe existir en `API_KEYS` o el servicio no arranca. |
| `401` | Falta la clave o no coincide. | `auth_rejected` con `reason` `missing` o `invalid`. Comprueba la clave del consumidor contra `API_KEYS`. |
| `400 request blocked by input policy` | El guardián vio una frase de prompt injection. | `audit` `input_blocked` y `security.blocked_inputs`. Si es un falso positivo recurrente, repórtalo para ajustar `INJECTION_PHRASES` (`app/guard.py`) con su prueba. |
| `/ready` en `503` o despliegue fallido | Falta un dato (directorio, políticas o precios) o compliance rechazó la configuración. | El check en `"error"` dice cuál; el `ConfigError` del arranque nombra la variable y la regla, nunca el valor. |
| No aparecen trazas en LangSmith | El producto no está trazando, o las trazas llegan a otro proyecto u otra región. | En orden: (1) que exista `LANGSMITH_TRACING=true` en Render > Environment: vale `false` por omisión y `render.yaml` no la define, así que con solo `LANGSMITH_API_KEY` no se traza nada; (2) que `LANGSMITH_API_KEY` tenga valor; (3) el proyecto: sin `LANGSMITH_PROJECT` las trazas van a `default`, búscalas ahí o en el proyecto que pusiste; (4) la región: si la cuenta es de Europa, falta `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`. Tras cambiar una variable, espera el reinicio y manda una pregunta nueva. `HIDE_INPUTS` y `HIDE_OUTPUTS` siguen en `true`. |
