# Costos del HR Assistant

Palancas de costo, evidencia contra la línea base y trade-offs entre costo y calidad. El costo
de cada respuesta sale de `data/model_prices.json` (USD por millón de tokens, copia de
`spec/model_prices.json`, tomada de la página de precios de Workers AI):

| Modelo | Entrada | Salida |
| --- | --- | --- |
| `MODEL_SMALL` = `@cf/meta/llama-3.1-8b-instruct-fast` | 0.045 | 0.384 |
| `MODEL_LARGE` = `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 0.293 | 2.253 |

El modelo grande cuesta unas 6.5 veces más por token de entrada y unas 5.9 veces más por token
de salida. `cost_usd` de cada respuesta suma la llamada del supervisor (si la hubo, siempre con
`MODEL_SMALL`) y las del especialista con el modelo que contestó (`app/pipeline.py`, `_cost`).

Ver también: [arquitectura](architecture.md), [seguridad](security.md),
[operación](operations.md) y los ADR [0008](adr/0008-rule-based-routing-and-history-window.md),
[0013](adr/0013-supervisor-rules-before-model.md),
[0014](adr/0014-guard-and-reviewer-in-code.md) y [0015](adr/0015-in-process-answer-cache.md).

## Evidencia: `verification evaluate`

Salida de `uv run python -m verification evaluate` con el modelo simulado: responde igual que
siempre, pero cada uno de los dos modelos se cobra con su precio real de Workers AI, así que la
comparación no usa red ni cuota. Cifras medidas después de la corrección 2 (adenda 2 del punto 3
de `spec/05-reto.md`, «Políticas ancladas al texto»).

| Configuración | Qué corre | Calidad | `cost_usd` | `input_tokens` |
| --- | --- | --- | --- | --- |
| `baseline` | `verification/eval_set.json` con 10 mensajes de historial de relleno; `ROUTING=false`, `HISTORY_WINDOW=1000` | 100 % | 0.000922 | 1738 |
| `levers` | El mismo conjunto e historial, con la configuración por omisión (`ROUTING=true`, `HISTORY_WINDOW=6`) | 100 % | 0.000126 | 1168 |
| `no_cache` | `verification/eval_set_reto.json` (6 preguntas de directorio y políticas) repetido 3 veces, sin historial; `ANSWER_CACHE_TTL_SECONDS=0` | 100 % | 0.000252 | 1359 |
| `cache` | Las mismas 18 preguntas con `ANSWER_CACHE_TTL_SECONDS=300` | 100 % | 0.000084 | 453 |

Ahorro:

| Comparación | Costo | Tokens de entrada | Calidad |
| --- | --- | --- | --- |
| Palancas contra línea base | 0.000126 / 0.000922 = 0.137 -> **-86 %** (-86.3 %) | 1168 / 1738 = 0.672 -> -33 % (-32.8 %) | 100 % -> 100 % |
| Caché encendida contra apagada | 0.000084 / 0.000252 = 0.333 -> **-67 %** (-66.7 %) | 453 / 1359 = 0.333 -> -67 % (-66.7 %) | 100 % -> 100 % |

Lectura de los números:

- En las palancas el costo baja mucho más que los tokens (-86 % contra -33 %). Los tokens bajan
  por la ventana de historial; el resto del ahorro viene del enrutador, que manda las preguntas
  simples al modelo pequeño, más barato por token. `baseline` y `levers` no cambiaron con la
  corrección 2.
- En la caché, de cada pregunta repetida 3 veces solo la primera llega a los modelos: 6 fallos y
  12 aciertos (tasa 66.7 %). Por eso costo y tokens bajan exactamente a un tercio
  (0.000252 / 3 = 0.000084; 1359 / 3 = 453). El costo por pregunta pasa de 0.0000140 a
  0.0000047 USD.
- **Por qué bajaron `no_cache` y `cache`** (antes 0.000308 / 2184 tokens y 0.000103 / 728): con
  `rule:policy` la política llega en código (`_ground`, `ground_policy`) y el especialista
  `policy` ya no gasta una vuelta al modelo para pedir `search_policy`, así que cada pregunta de
  políticas hace una llamada menos (-18 % de costo y -38 % de tokens en `no_cache`).
- Los costos se imprimen con 6 decimales; los porcentajes son aproximados a esa precisión.

### La regla de aprobación

`verification/evaluate.py` termina con código 0 solo si se cumplen las cuatro condiciones:

1. `verdict(baseline, levers)`: calidad de `levers` mayor o igual que la de `baseline`, y costo
   estrictamente menor.
2. `verdict(no_cache, cache)`: lo mismo para la caché de respuestas.
3. `no_regression(levers)`: la calidad de `levers` es exactamente 100 %.
4. `no_regression(cache)`: la calidad de `cache` es exactamente 100 %.

`no_regression` existe porque el veredicto relativo no basta: una regresión que bajara la
calidad de la línea base y de las palancas por igual pasaría `verdict`. Con ella, el conjunto
original se sigue respondiendo completo, como en las sesiones 1 a 4.

## Palancas

### 1. Supervisor con reglas antes que modelo (`app/supervisor.py`, ADR 0013)

El supervisor elige el especialista con reglas en código, sin llamar a ningún modelo: id
`EMP-dddd` (`rule:employee`), departamento que existe (`rule:department`) o palabra clave de
`data/policies.json` (`rule:policy`). Solo si ninguna aplica hace una llamada a `MODEL_SMALL`,
sin historial (`model`; una respuesta inválida da `model_invalid` y `directory`).

- Ahorro: una pregunta con regla cuesta lo mismo que en la sesión 4 (cero llamadas extra; lo
  comprueba `tests/test_supervisor.py`, que cuenta 0 llamadas al modelo con reglas). Una sin
  regla paga una llamada corta al modelo pequeño.
- No aparece aislada en la tabla: está activa en las cuatro configuraciones. Se ve en
  `/metrics` (`supervisor.rule` contra `supervisor.model`) y en `supervisor_route` de
  `agent_run`.
- Trade-off: en preguntas mixtas una regla puede elegir mal; la precedencia es fija y
  explicable.

### 2. Política consultada en código (`app/specialists.py`, `ground_policy`; ADR 0014)

Cuando el supervisor elige `policy` por `rule:policy`, `AskPipeline._ground` pone el texto de la
política (el mismo que devolvería `search_policy`) como mensaje «Resultado de la herramienta: »
antes de la primera llamada al modelo. Nació como control de calidad (corrección 2, ver
[seguridad](security.md)), pero también ahorra.

- Ahorro: una vuelta menos al modelo por pregunta de políticas; explica la baja de `no_cache` y
  `cache` frente a la medición anterior.
- Trade-off: la primera llamada lleva el texto de la política aunque el modelo no lo hubiera
  pedido; las políticas son cortas y esa vuelta extra costaba más.

### 3. Modelo pequeño por omisión: enrutador (`app/levers.py`, `choose_model`, ADR 0008)

Con `ROUTING=true`, el especialista usa `MODEL_SMALL` salvo que la pregunta pase de
`ROUTER_MAX_CHARS` (80) o tenga «compara», «resume», «explica», «por qué», «analiza» o «todos»;
esas van a `MODEL_LARGE`. El motivo sale en `route` (`simple`, `long_question`,
`keyword:<palabra>`, `routing_off`).

- Ahorro: es la palanca que más pesa en el -86 % (la línea base corre todo con `MODEL_LARGE`).
- Trade-off: una pregunta compleja que no tenga palabra clave ni sea larga va al modelo pequeño
  y puede salir peor. El conjunto de evaluación lo vigila (calidad 100 %).

### 4. Ventana de historial (`app/levers.py`, `trim_history`)

Solo se mandan los últimos `HISTORY_WINDOW` mensajes (6 por omisión; la línea base usa 1000).

- Ahorro: explica la baja de tokens de entrada (-33 %) con el historial de 10 mensajes.
- Trade-off: el modelo pierde el contexto más viejo de una conversación larga.

### 5. Tope de salida (`MODEL_MAX_TOKENS`, `app/gateway.py`, `GatewayModel._body`)

Cada llamada al gateway manda `max_tokens` = `MODEL_MAX_TOKENS` (300 por omisión). Pone techo al
costo de salida de una llamada: 300 tokens cuestan como máximo unos 0.000676 USD con
`MODEL_LARGE` y 0.000115 USD con `MODEL_SMALL`.

- No aparece en la tabla: el valor es el mismo en `baseline` y `levers`, y el modelo simulado
  contesta corto. Su efecto se ve con el modelo real.
- Trade-off: una respuesta larga (una lista de un departamento grande) puede quedar cortada; el
  revisor además recorta a `MAX_ANSWER_CHARS` (1500).

### 6. Caché de respuestas en proceso (`app/cache.py`, ADR 0015)

Con `ANSWER_CACHE_TTL_SECONDS` > 0, una pregunta sin historial y sin PII cuya forma normalizada
(minúsculas, sin acentos, espacios colapsados) ya se respondió dentro del TTL sale de la
memoria del proceso: `cached: true`, `cost_usd: 0`, tokens y pasos en 0, `agents: ["guard",
"cache"]`. Máximo `ANSWER_CACHE_MAX_ENTRIES` (256) entradas; sale la más vieja. Apagada por
omisión; en Render va en 300 s (`render.yaml`).

- Ahorro: -67 % con cada pregunta repetida 3 veces; en general, proporcional a la tasa de
  aciertos (`cache.hit_rate` en `/metrics` y en el tablero).
- Trade-off: una respuesta puede tener hasta 300 s de antigüedad (los datos son de solo
  lectura); la caché es por proceso y se vacía en cada despliegue, reinicio o cuando Render
  duerme el servicio del plan gratuito; es compartida entre clientes porque todos ven los
  mismos datos. No guarda respuestas con historial, con PII, bloqueadas por el revisor
  (incluidas las de cifras de política no ancladas), de respaldo ni las que no terminaron en
  `answer`. El guardián siempre corre antes.

### 7. Caché de AI Gateway (`CACHE_TTL_SECONDS`, `app/gateway.py`)

Con `CACHE_TTL_SECONDS` > 0, cada llamada manda `cf-aig-cache-ttl`; si AI Gateway responde
`cf-aig-cache-status: HIT`, esa llamada cuenta en `cached_calls`.

- Complementa a la caché de respuestas: ayuda cuando el cuerpo de la llamada es idéntico aunque
  la petición tenga historial (por ejemplo, la clasificación del supervisor, que nunca lleva
  historial).
- No se mide en `verification evaluate` (el modelo simulado no pasa por el gateway) y está
  apagada por omisión: `render.yaml` no la define. Para usarla se agrega `CACHE_TTL_SECONDS` en
  Render > Environment.
- Trade-off: igual que la caché de respuestas, respuestas de hasta `CACHE_TTL_SECONDS` de
  antigüedad.

## Respaldo y reintentos: costo de la resiliencia

Los reintentos (`MODEL_RETRIES`, solo ante timeout, `429` o `5xx`) y el respaldo
(`MODEL_FALLBACK`) pueden sumar llamadas. Una respuesta de respaldo con `MODEL_LARGE` cuesta más
que la del modelo pequeño elegido; por eso cuentan en `fallbacks` de `/metrics` y en `fallback`
de `agent_run`, y no entran a la caché.

## Cómo reproducirlo

Desde la raíz del repositorio:

```bash
uv run python -m verification evaluate   # imprime las cuatro filas; código 0 si pasa
```

Para resumir el costo real de un log (local o descargado de Render):

```bash
cd product
uv run uvicorn app.main:app > uvicorn.log 2>&1     # en otra terminal, haz preguntas
python scripts/cost_report.py uvicorn.log          # o: python scripts/cost_report.py < uvicorn.log
```

`scripts/cost_report.py` lee las líneas `agent_run` (ignora las que no son JSON, como las de
uvicorn) e imprime peticiones, costo total y por petición, tokens, la tasa de caché
(`cached: true` entre todas las corridas) y tablas por cliente, por especialista y por modelo.
Termina con código 2 si el archivo no existe. La CI lo corre sobre `uvicorn.log` después de la
prueba de carga (trabajo `e2e` de `.github/workflows/ci.yml`).
