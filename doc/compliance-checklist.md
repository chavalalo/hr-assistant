# Lista de compliance del HR Assistant

Las reglas de producción se revisan en código al arrancar: con
`ENVIRONMENT=production`, `create_app` llama a `app.compliance.enforce`, y si alguna
regla falla lanza `ConfigError` y el proceso no arranca. El mensaje nombra la variable
y la regla, nunca un valor. En `development` estas tres reglas no se exigen; las demás
filas valen siempre.

| Regla | Dónde está en el código | Cómo se comprueba |
| --- | --- | --- |
| En producción `MODEL_PROVIDER` no puede ser `fake`. | `app/compliance.py`, `_model_violations`; se aplica en `app/main.py`, `create_app` -> `enforce` | `tests/test_compliance.py`; escenario «Production refuses to start» de `tests/features/security.feature` (the fake model); contrato `test_production_refuses_the_fake_model` (`import app.main` termina con código distinto de 0) |
| En producción `API_KEYS` no puede estar vacía. | `app/compliance.py`, `_api_key_violations` | `tests/features/security.feature` (no API keys) |
| En producción cada clave tiene 16 caracteres o más. | `app/compliance.py`, `_api_key_violations` (`MIN_API_KEY_CHARS`) | `tests/test_compliance.py` (claves de 15 y de 16); `tests/features/security.feature` (a key of 15 characters) |
| En producción, si se piden trazas (`LANGSMITH_TRACING=true`), `HIDE_INPUTS` y `HIDE_OUTPUTS` valen `true`. | `app/compliance.py`, `_tracing_violations` (usa `langsmith_tracing_requested` de `app/config.py`) | `tests/test_compliance.py`; `tests/features/security.feature` (tracing that shows the inputs) |
| `API_KEYS` mal formada impide arrancar; el error dice la posición y el largo, nunca el valor. | `app/auth.py`, `parse_api_keys` y `_malformed`; `app/config.py`, `_security_settings` (`from None`) | `tests/test_auth.py`; contrato `test_a_broken_api_keys_never_leaks_the_key` (busca la clave en `stderr`) |
| `POST /ask` y `GET /metrics` exigen `X-API-Key`; sin clave o con una inválida, `401`. | `app/main.py`, `_client_dependency` (`require_client`) | `tests/features/security.feature`; `tests/test_security_api.py`; contratos `test_asking_without_a_key_returns_401` y `test_asking_with_a_wrong_key_returns_401` |
| `GET /`, `GET /health`, `/docs` y `/openapi.json` no piden clave. | `app/main.py`, `_add_routes` (solo `/ask` y `/metrics` llevan la dependencia) | `tests/features/security.feature` (Health, the page and the docs); contrato `test_health_and_page_need_no_key` |
| Las claves se comparan en tiempo constante, contra todas. | `app/auth.py`, `identify_client` (`hmac.compare_digest`, sin salida temprana) | `tests/test_auth.py`; revisión de código |
| La clave nunca se escribe en el log, la traza, un error ni `repr`. | `app/auth.py` (`ApiClient.key` con `repr=False`); `app/config.py` (`api_clients` con `repr=False`); `app/main.py` (solo se registra `client` o `reason`); `app/tracing.py` (metadatos `request_id` y `client`) | `tests/test_auth.py` (`repr`); `tests/test_security_api.py` y `tests/features/security.feature` (buscan la clave en todo el log); `tests/test_tracing.py` (metadatos exactos) |
| El nombre del cliente va en `request`, `audit`, `agent_run` y en la traza. | `app/main.py` (middleware, `_log_agent_run`, `_answer`); `app/tracing.py` | `tests/features/security.feature` (The client name is logged); `tests/test_tracing.py` |
| Límite por cliente: más de `RATE_LIMIT_PER_MINUTE` en 60 s -> `429` con `Retry-After`; el reloj se inyecta. | `app/ratelimit.py`, `RateLimiter`; `app/main.py`, `require_client` (después de la clave) | `tests/test_ratelimit.py` (reloj fijo); `tests/features/security.feature`; `tests/test_security_api.py`; contrato `test_too_many_requests_returns_429_with_retry_after` |
| La página guarda la clave solo en `sessionStorage` y la manda en `X-API-Key`; el campo es de tipo contraseña. | `app/static/index.html` | Pruebas de punta a punta en `e2e/`; contrato `test_health_and_page_need_no_key` (el campo `api-key` está en la página) |
