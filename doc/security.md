# Seguridad del HR Assistant

Modelo de amenazas y controles del reto (`spec/05-reto.md`, puntos 2, 3, 4, 5, 6 y 8), más los
de la sesión 4 que siguen vigentes. Cada control dice dónde vive en el código y qué prueba lo
comprueba. Las rutas de código son relativas a `product/`; las pruebas están en
`product/tests/` y los contratos de la fábrica en `verification/contract/`.

Ver también: [arquitectura](architecture.md), [costos](costs.md), [operación](operations.md),
[lista de compliance](compliance-checklist.md) y el ADR
[0014 Guardián de entrada y revisor de salida en código](adr/0014-guard-and-reviewer-in-code.md).

## Qué se protege

- Los datos del directorio de empleados y de las políticas (solo lectura, iguales para todos).
- Los datos personales que una persona escriba en su pregunta o en el historial.
- Las instrucciones del sistema (`app/prompts.py`) y el comportamiento de los agentes.
- Los secretos: `API_KEYS`, `CF_API_TOKEN`, `CF_AIG_TOKEN` y `LANGSMITH_API_KEY`.
- Las métricas de negocio (`GET /metrics`): costo y uso por cliente.
- El presupuesto de Workers AI.

## Quién ataca y por dónde

| Actor | Entrada |
| --- | --- |
| Persona con clave válida que intenta desviar al asistente | `question` y mensajes `user` del `history` de `POST /ask` |
| Alguien sin clave o con una clave robada o adivinada | `X-API-Key` en `POST /ask` y `GET /metrics` |
| Cliente legítimo que abusa (muchas peticiones) | `POST /ask` en ráfaga |
| Cliente con clave que no debe ver costos ni uso de otros | `GET /metrics` y el tablero `GET /dashboard` |
| El propio modelo (salida no confiable) | Respuesta del especialista y argumentos de herramientas: puede inventar ids o repetir datos personales |
| Error de configuración al publicar | Variables de Render, `render.yaml`, logs y trazas |

## Amenazas

| Id | Amenaza | Controles |
| --- | --- | --- |
| A1 | Prompt injection: pedir ignorar instrucciones, revelar el prompt o cambiar de rol. | C1 |
| A2 | Datos personales que llegan al modelo, al log o a la traza. | C2, C10, C11 |
| A3 | Respuesta no anclada a los datos: el modelo inventa un empleado `EMP-dddd`. | C3 |
| A4 | Uso sin autorización o suplantación de un cliente. | C4 |
| A5 | Abuso de costo o denegación de servicio por ráfagas. | C5 |
| A6 | Un cliente cualquiera lee costos y uso de todos. | C6 |
| A7 | Secretos en el repositorio, en el Blueprint, en un error o en un `repr`. | C7, C8 |
| A8 | Producción arranca con configuración insegura (modelo simulado, claves cortas, trazas con texto, `/metrics` abierto). | C9 |
| A9 | No poder reconstruir qué pasó, o que la bitácora misma filtre datos. | C10, C11 |

## Controles

| Id | Control | Dónde vive | Qué prueba lo comprueba |
| --- | --- | --- | --- |
| C1 | **Guardián contra prompt injection.** Frases normalizadas (sin acentos ni mayúsculas, con cualquier espacio) en la pregunta y en los mensajes `user` del historial: «ignora/olvida ... instrucciones», «ignore/forget previous instructions», «revela ... prompt», «prompt del sistema», «system prompt», «actua como», «act as», «modo desarrollador», «developer mode», «jailbreak». Responde `400 {"detail": "request blocked by input policy", "request_id": ...}` antes de llamar a cualquier modelo. Los mensajes `assistant` no bloquean. | `app/guard.py` (`INJECTION_PHRASES`, `is_injection`, `inspect`, `InputBlocked`); `app/pipeline.py` (`_guard`); `app/main.py` (ruta `/ask`, `BLOCKED_STATUS`) | `tests/test_guard.py`; `tests/features/guardrails.feature` (Prompt injection is blocked before any model is called: espía sin llamadas, mayúsculas, sin acentos e historial); contratos `test_prompt_injection_is_blocked_before_the_model` y `test_prompt_injection_in_the_history_is_blocked` |
| C2 | **Redacción de PII.** En la pregunta, en todo el historial y en la respuesta, en orden fijo: `email` -> `[EMAIL]`, `curp` -> `[CURP]`, `rfc` -> `[RFC]`, `card` (13 a 19 dígitos que pasan Luhn) -> `[CARD]`, `nss` (11 dígitos) -> `[NSS]`, `phone` (10 dígitos, `+52` opcional, con separadores) -> `[PHONE]`. Los ids `EMP-dddd` nunca son PII. Los tipos salen en `pii_redacted`. Una pregunta con PII no usa la caché de respuestas. | `app/pii.py` (`RULES`, `redact`, `passes_luhn`); `app/guard.py` (entrada); `app/reviewer.py` (salida); `app/pipeline.py` (`_audit_pii`, `_cache_key`) | `tests/test_pii.py` (cada tipo, tarjeta sin Luhn intacta, `EMP-0001` intacto, tipos ordenados); `tests/test_guard.py` (historial); `tests/test_reviewer.py`; `tests/features/guardrails.feature` (Personal data is replaced before the model sees it); contratos `test_personal_data_is_redacted_from_question_and_answer`, `test_card_numbers_and_phones_are_detected` y `test_questions_with_history_or_pii_skip_the_cache` |
| C3 | **Revisor de grounding.** Si la respuesta cita un `EMP-dddd` que no está en el directorio **y que la persona no escribió en su pregunta** (comparación sin mayúsculas contra la pregunta ya redactada), se reemplaza por «No pude verificar la respuesta con el directorio. Intenta de nuevo.». Después recorta a `MAX_ANSWER_CHARS`. Una respuesta bloqueada no entra a la caché. | `app/reviewer.py` (`employee_ids`, `mentions_unknown_employee`, `review`, `UNVERIFIED_ANSWER`); `app/pipeline.py` (`_review`, `_cache_store`) | `tests/test_reviewer.py` (PII y recorte); `tests/features/guardrails.feature` (id inventado `EMP-0777` reemplazado; `EMP-9999` escrito por la persona no se bloquea) |
| C4 | **Claves por cliente.** `API_KEYS` con forma `cliente:clave,...`; `X-API-Key` en `POST /ask` y `GET /metrics`; comparación con `hmac.compare_digest` contra todas, sin salida temprana; `401 {"detail": "invalid or missing API key"}`. El log lleva el nombre del cliente, nunca la clave. | `app/auth.py` (`parse_api_keys`, `identify_client`, `ApiClient.key` con `repr=False`); `app/main.py` (`_client_dependency`, `require_client`) | `tests/test_auth.py`; `tests/test_security_api.py`; `tests/features/security.feature`; contratos `test_asking_without_a_key_returns_401`, `test_asking_with_a_wrong_key_returns_401` y `test_a_broken_api_keys_never_leaks_the_key` |
| C5 | **Límite de peticiones.** Ventana deslizante de 60 s por cliente, `RATE_LIMIT_PER_MINUTE` (30 por omisión); `429 {"detail": "rate limit exceeded"}` con `Retry-After`. Se revisa después de la clave; las rechazadas no cuentan. | `app/ratelimit.py` (`RateLimiter`); `app/main.py` (`require_client`) | `tests/test_ratelimit.py` (reloj fijo); `tests/test_security_api.py`; `tests/features/security.feature` (A client over the limit); contrato `test_too_many_requests_returns_429_with_retry_after` |
| C6 | **Mínimo privilegio en `/metrics`.** Con `METRICS_CLIENTS` con valor, otro cliente con clave válida recibe `403 {"detail": "forbidden"}` (orden 401 -> 429 -> 403), con `audit` `access_denied` (`path`) y contador `security.access_denied`; la lectura permitida deja `metrics_read`. Vacía: todos leen (solo desarrollo). El tablero no trae datos en el HTML y muestra «Sin permiso para ver métricas» con `403`. | `app/auth.py` (`can_read_metrics`); `app/main.py` (ruta `/metrics`, `FORBIDDEN_STATUS`); `app/static/dashboard.html` | `tests/features/guardrails.feature` (Only metrics clients read the metrics); `tests/test_api.py` (`test_dashboard_is_public_and_carries_no_data_or_key`); contratos `test_only_metrics_clients_can_read_metrics` y `test_dashboard_page_is_public_and_has_no_data` |
| C7 | **Secretos solo en Render > Environment.** En `render.yaml`, `API_KEYS`, `CF_ACCOUNT_ID`, `CF_API_TOKEN` y `METRICS_CLIENTS` van con `sync: false` (Render pide el valor, no se guarda en el repositorio). `CF_AIG_TOKEN` y `LANGSMITH_API_KEY` no están en el Blueprint: se agregan a mano en Render > Environment si se usan. `.env` no entra a la imagen ni al repositorio; `.env.example` no lleva valores secretos. `CF_API_TOKEN`, `CF_AIG_TOKEN` y `api_clients` tienen `repr=False`; los errores de `ConfigError` nombran la variable, nunca el valor. | `render.yaml`; `.env.example`; `app/config.py`; `app/auth.py` (`_malformed`) | `tests/test_config.py` (`test_settings_never_show_the_cloudflare_token`, `test_gateway_without_any_cloudflare_variable_prevents_startup`, `test_settings_never_keep_the_langsmith_key`); `tests/test_auth.py` (`test_settings_repr_never_shows_the_api_keys`). Que `render.yaml` use `sync: false` se comprueba por revisión del archivo: no hay prueba automática (ver «Riesgos abiertos»). |
| C8 | **`CF_AIG_TOKEN` no se filtra.** Si tiene valor, el gateway manda `cf-aig-authorization: Bearer <token>`; si no, el encabezado no va. Los errores del gateway son mensajes fijos con `from None` (sin URL, cuerpo ni token); la respuesta `502` y la línea `error` solo llevan el tipo. | `app/gateway.py` (`AIG_AUTH_HEADER`, `GatewayModel._headers`, `GatewayModel.complete`); `app/config.py` (`cf_aig_token` con `repr=False`); `app/main.py` (ruta `/ask`, `ModelUnavailable`) | `tests/test_resilience.py` (`test_aig_token_goes_in_its_header_and_never_in_an_error`: encabezado, error y `repr`); `tests/test_config.py` (`test_challenge_settings_have_safe_defaults_and_reject_invalid_values`: el valor no sale en ningún `ConfigError`); contrato `test_aig_token_never_leaks_on_a_bad_config` (busca el valor en `stdout` y `stderr` de un arranque fallido) |
| C9 | **Compliance como código.** Con `ENVIRONMENT=production`, `create_app` llama a `enforce` y el proceso no arranca si: `MODEL_PROVIDER=fake`; `API_KEYS` vacía o con una clave de menos de 16 caracteres; trazas pedidas sin `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true`; `METRICS_CLIENTS` vacía o con un cliente que no está en `API_KEYS`. El mensaje dice la variable y la posición, nunca un valor. | `app/compliance.py` (`_model_violations`, `_api_key_violations`, `_tracing_violations`, `_metrics_clients_violations`, `enforce`); `app/main.py` (`create_app`) | `tests/test_compliance.py`; `tests/features/security.feature` (Production refuses to start with unsafe settings); contratos `test_production_refuses_the_fake_model` y `test_production_requires_metrics_clients_from_api_keys`. Detalle por regla en [compliance-checklist.md](compliance-checklist.md). |
| C10 | **Auditoría sin PII.** Una línea `audit` con `client` y `action` por acción: `tool_call` (`tool`, `args`), `input_blocked` (`reason: prompt_injection`), `pii_redacted` (`location`, `types`, `count`), `output_blocked` (`reason: unknown_employee_id`), `access_denied` (`path`) y `metrics_read`. Los `args` de `tool_call` los escribe el modelo y pueden copiar un dato personal que vio antes: cada texto pasa por `redact` y después se recorta, `redact(value).text[:AUDIT_ARG_MAX_CHARS]` (200 caracteres), así el log solo lleva marcadores como `[EMAIL]`. `agent_run` lleva solo conteos, tipos, modelo, costo y banderas (`question_chars`, `pii_types`, `cached`, `fallback`...), nunca el texto. La línea `error` lleva solo `error_type`. | `app/pipeline.py` (`_guard`, `_audit_pii`, `_review`, `_record`, `_audit_args`); `app/pii.py` (`redact`); `app/main.py` (ruta `/metrics`, middleware) | `tests/test_audit_redaction.py` (`test_tool_call_audit_redacts_and_trims_model_arguments`: modelo espía que pide `search_by_department` con un correo y un teléfono; el log trae `[EMAIL]` y `[PHONE]`, recortado, y nunca los valores); `tests/features/guardrails.feature` (cada `audit` y «the log never contains»); `tests/features/observability.feature` (Asking writes request, agent_run and audit lines without personal text; error sin mensaje); `tests/features/security.feature` (The client name is logged and the key never is); `tests/test_api.py` (la pregunta no está en el log) |
| C11 | **Trazas sin texto en raíz, guardián, supervisor y revisor.** `run_traced` envuelve una función sin argumentos (el run no tiene entradas) y su salida es un resumen: `_outcome_summary` (raíz `request`), `_guard_summary` (`agent.guard`), `_decision_summary` (`agent.supervisor`) y `_review_summary` (`agent.reviewer`), con tipos, conteos y decisiones. El especialista recibe solo texto ya redactado. Con `HIDE_INPUTS=true` y `HIDE_OUTPUTS=true` (por omisión, y obligatorios en producción con trazas) el cliente de LangSmith no manda texto. Metadatos: `request_id`, `client` y `specialist`, nunca la clave. | `app/tracing.py` (`run_traced`, `trace_metadata`, `LangSmithTracer`); `app/pipeline.py` (funciones `_*_summary`); `app/compliance.py` (`_tracing_violations`) | `tests/test_tracing.py` (`hide_inputs`/`hide_outputs` en el cliente; metadatos exactos sin clave); `tests/test_compliance.py`. Que los runs `request`, `agent.guard`, `agent.supervisor` y `agent.reviewer` no lleven entradas se comprueba hoy por revisión de código: no hay prueba unitaria que lo afirme (ver «Riesgos abiertos»). |

## Riesgos abiertos

Controles que hoy no tienen una prueba automática que los sostenga.

| Riesgo | Mitigación pendiente |
| --- | --- |
| Nada impide que un cambio futuro le pase argumentos (texto de la persona) a los runs `request`, `agent.guard`, `agent.supervisor` o `agent.reviewer` (C11). | qa-unit: una prueba con el doble de `langsmith` de `tests/test_tracing.py` que llame a `AskPipeline.answer` y compruebe que esos cuatro runs se llaman sin argumentos y que su salida no contiene la pregunta. |
| Nada impide que un cambio en `render.yaml` ponga el valor de `API_KEYS`, `CF_ACCOUNT_ID`, `CF_API_TOKEN` o `METRICS_CLIENTS` en el Blueprint en lugar de `sync: false`, o agregue ahí `CF_AIG_TOKEN` o `LANGSMITH_API_KEY` con valor (C7). | deploy o qa-unit: una prueba que lea `render.yaml` y exija `sync: false` en esas cuatro variables y la ausencia de las dos opcionales. Hasta entonces se revisa el archivo en cada cambio. |

## Límites aceptados del diseño

No son pendientes: son decisiones con su mitigación, documentadas para que nadie las tome por
garantías.

| Límite | Mitigación |
| --- | --- |
| La lista de frases del guardián no cubre todas las formas de injection (otros idiomas, paráfrasis, texto codificado). | Lista corta a propósito para evitar falsos positivos. Se amplía con evidencia del contador `security.blocked_inputs`. El especialista solo tiene herramientas de lectura: el daño de un injection que pase es acotado. |
| La PII por expresiones regulares no detecta nombres, direcciones ni formatos fuera de la lista. | Los tipos son los de la spec. Los datos del directorio ya son de RH; lo que se protege es lo que escribe la persona o repite el modelo. |
| El límite y las métricas viven en la memoria del proceso. | Un solo worker (ADR 0005); con varios procesos el límite se multiplicaría. |
| La caché de respuestas es compartida entre clientes. | Correcto mientras todos vean los mismos datos (ADR 0015). Nunca guarda preguntas con historial o PII ni respuestas bloqueadas o de respaldo. |
| Un `EMP-dddd` inexistente que la persona escribió puede aparecer en la respuesta. | Es lo que pide la adenda del punto 3: la respuesta puede decir «no existe». Un id que el modelo inventa sí se bloquea (ADR 0014). |
