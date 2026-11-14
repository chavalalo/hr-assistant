# 0005 Métricas en memoria por proceso

Estado: propuesto (sesión 2)

## Contexto

Se pide `GET /metrics` con peticiones, tasa de error, latencia p50/p95, tokens y si se cumple
el SLO (`SLO_P95_MS`). El ADR 0001 exige una API sin estado para escalar con más copias, y no
hay base de datos ni sistema de métricas externo.

## Decisión

- `Metrics` vive en memoria dentro de cada proceso, creado por `create_app` e inyectable.
- Guarda contadores (peticiones, respuestas 5xx, tokens) y una ventana acotada de las últimas
  `LATENCY_WINDOW = 1000` latencias; p50 y p95 se calculan por rango más cercano.
- `error_rate` cuenta solo 5xx. `met` es `p95 < slo_p95_ms`; sin datos, `met` es `true`.
- Un `threading.Lock` protege el estado porque FastAPI ejecuta rutas `def` en varios hilos.
- La respuesta incluye `pid` para saber de qué copia vienen los números.

## Consecuencias

- Es estado operativo, no de negocio: perderlo al reiniciar no afecta respuestas, así que el
  ADR 0001 sigue vigente.
- Con varias copias cada una reporta lo suyo; agregar entre procesos queda para un sistema
  externo (por ejemplo, a partir del log JSON).
- La memoria está acotada por la ventana; los percentiles reflejan tráfico reciente.
