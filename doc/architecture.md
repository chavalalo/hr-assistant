# Arquitectura del HR Assistant (sesiones 1 a 4)

El HR Assistant responde preguntas del personal de RH sobre empleados. Es una API FastAPI sin
estado con una página web, un solo agente con bucle con tope y un modelo detrás de una
interfaz. La sesión 2 agrega observabilidad (id por petición, log JSON, métricas, trazas
opcionales). La sesión 3 agrega el modelo real (Workers AI vía AI Gateway) y cuatro palancas de
costo. La sesión 4 lo lleva a producción: clave por cliente, límite de peticiones, compliance
como código, contenedor, CI en cuatro etapas y publicación en Render solo si el CI pasa.

## Componentes

```mermaid
flowchart LR
    subgraph Navegador
        UI["index.html<br/>clave en sessionStorage<br/>historial local"]
    end
    subgraph API["FastAPI (main.py, sin estado de negocio)"]
        MW["middleware<br/>X-Request-ID, latencia, 500"]
        AUTH["require_client<br/>401 / 429"]
        ASK["POST /ask<br/>502 si el modelo falla"]
        METRICS["GET /metrics"]
        PUBLIC["GET / , /health, /docs<br/>sin clave"]
    end
    CFG["config.py<br/>Settings.from_env"]
    COMP["compliance.py<br/>enforce al arrancar"]
    KEYS["auth.py<br/>parse_api_keys, compare_digest"]
    RL["ratelimit.py<br/>ventana de 60 s por cliente"]
    CLK["clock.py"]
    LEV["levers.py"]
    COST["costs.py"]
    LOG["logs.py<br/>client, nunca la clave"]
    MET["metrics.py"]
    TR["tracing.py<br/>request_id + client"]
    AGENT["agent.py"]
    LLM["llm.py / gateway.py"]
    CF[("Cloudflare AI Gateway")]
    DIR["directory.py"]

    UI -- "X-API-Key + question + history" --> MW
    MW --> PUBLIC
    MW --> AUTH
    AUTH --> KEYS
    AUTH --> RL
    RL --> CLK
    AUTH -- "client" --> ASK
    AUTH -- "client" --> METRICS
    CFG --> KEYS
    CFG --> COMP
    COMP -. "ConfigError: no arranca" .-> API
    ASK --> LEV
    ASK --> COST
    ASK --> AGENT
    TR -. "envuelve" .-> AGENT
    AGENT --> LLM
    LLM --> CF
    AGENT --> DIR
    ASK --> LOG
    MW --> LOG
    AUTH -- "auth_rejected, rate_limited" --> LOG
    ASK --> MET
    METRICS --> MET
```

## Publicación

```mermaid
flowchart LR
    DEV["Fábrica<br/>verificaciones en verde"] --> OK{"Persona aprueba<br/>output/approved.txt"}
    OK -- "si" --> PUB["scripts/publish.py<br/>repo privado en GitHub"]
    PUB --> CI
    subgraph CI["GitHub Actions (ci.yml)"]
        S["style<br/>pylint 88"] --> U["unit<br/>cobertura 80 %"] --> E["e2e<br/>Playwright, modelo simulado"] --> D["docker<br/>docker build"]
    end
    D -- "checksPass" --> R["Render<br/>Blueprint render.yaml<br/>python:3.12-slim, sin root"]
    SEC[("Secretos en Render<br/>API_KEYS, CF_ACCOUNT_ID, CF_API_TOKEN")] -.-> R
    R --> COMPL{"compliance.enforce"}
    COMPL -- "falla" --> FAIL["despliegue fallido"]
    COMPL -- "pasa" --> LIVE["Live: /health"]
    LIVE --> SMOKE["verification production<br/>/health 200, sin clave 401, con clave 200"]
```

## Secuencia de una pregunta

```mermaid
sequenceDiagram
    participant W as Página web
    participant MW as Middleware
    participant AU as require_client
    participant RL as RateLimiter
    participant A as POST /ask
    participant G as Agent y modelo
    W->>MW: POST /ask + X-API-Key
    MW->>AU: petición con request_id
    alt sin clave o inválida
        AU-->>W: 401 invalid or missing API key
    else clave válida
        AU->>RL: check(client)
        alt pasa el límite
            RL-->>W: 429 rate limit exceeded + Retry-After
        else dentro del límite
            AU->>A: client
            A->>G: run (traza con request_id y client)
            G-->>A: answer, completions
            A-->>W: answer, model, route, cost_usd, request_id
        end
    end
    MW->>MW: log request con client y status
```

## Decisiones

- [0001 API sin estado con historial en el cliente](adr/0001-stateless-api.md)
- [0002 Modelo detrás de una interfaz e inyección de dependencias](adr/0002-model-interface-and-injection.md)
- [0003 Un solo agente con bucle con tope y protocolo JSON](adr/0003-bounded-agent-loop.md)
- [0004 Id por petición y log JSON sin datos personales](adr/0004-request-id-and-json-logs.md)
- [0005 Métricas en memoria por proceso](adr/0005-in-process-metrics.md)
- [0006 Trazas opcionales con LangSmith detrás de un Tracer](adr/0006-optional-langsmith-tracing.md)
- [0007 Modelo real detrás de la interfaz, con cliente HTTP inyectado](adr/0007-gateway-model-behind-interface.md)
- [0008 Enrutamiento por regla y ventana de historial](adr/0008-rule-based-routing-and-history-window.md)
- [0009 Costo por respuesta y modelos simulados con precio](adr/0009-cost-per-answer-and-priced-fake-models.md)
- [0010 Clave por cliente y límite de peticiones en memoria](adr/0010-per-client-api-keys-and-rate-limit.md)
- [0011 Compliance como código: el producto se niega a arrancar](adr/0011-compliance-as-code-at-startup.md)
- [0012 Contenedor, CI en cuatro etapas y Render con checksPass](adr/0012-container-ci-and-render-checks-pass.md)

## Configuración

| Variable | Por omisión | Validación |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development` o `production`; con `production` se aplican las reglas de compliance |
| `API_KEYS` | vacía | `cliente:clave,...`; secreto; error con posición y largo, nunca el valor |
| `RATE_LIMIT_PER_MINUTE` | `30` | Entero mayor que 0; por cliente |
| `MODEL_PROVIDER` | `fake` | `fake` o `gateway`; en producción no puede ser `fake` |
| `CF_ACCOUNT_ID`, `CF_GATEWAY_ID`, `CF_API_TOKEN` | vacía, `default`, vacía | Obligatorias con `gateway`; el token no se muestra nunca |
| `MODEL_SMALL` | `@cf/meta/llama-3.1-8b-instruct-fast` | No vacío y con precio |
| `MODEL_LARGE` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | No vacío y con precio |
| `ROUTING` | `true` | `true` o `false` |
| `ROUTER_MAX_CHARS` | `80` | Entero mayor que 0 |
| `HISTORY_WINDOW` | `6` | Entero mayor o igual a 0 |
| `MODEL_MAX_TOKENS` | `300` | Entero mayor que 0 |
| `MODEL_TEMPERATURE` | `0` | Decimal mayor o igual a 0 |
| `CACHE_TTL_SECONDS` | `0` | Entero mayor o igual a 0 (0: sin caché) |
| `PRICES_PATH` | `data/model_prices.json` | Relativo a `product/`; el archivo debe existir |
| `AGENT_MAX_STEPS` | `3` | Entero mayor que 0 |
| `MAX_QUESTION_CHARS` | `2000` | Entero mayor que 0 |
| `EMPLOYEES_PATH` | `data/employees.json` | Relativo a `product/`; el archivo debe existir |
| `SERVICE_NAME` | `hr-assistant` | Texto no vacío |
| `SLO_P95_MS` | `2000` | Entero mayor que 0 |
| `LANGSMITH_TRACING` | `false` | `true` o `false`; sin `LANGSMITH_API_KEY` no se traza |
| `HIDE_INPUTS` / `HIDE_OUTPUTS` | `true` | `true` o `false`; en producción con trazas deben ser `true` |
| `PORT` | `8000` | Lo pone Render; solo lo usa el `CMD` del contenedor |

Los secretos (`API_KEYS`, `CF_API_TOKEN`, `LANGSMITH_API_KEY`) nunca se escriben en el log, en
la traza, en un error, en `.env.example` ni en el repositorio: en Render van con `sync: false`.
