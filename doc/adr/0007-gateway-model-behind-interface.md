# 0007 Modelo real de Workers AI detrás de la interfaz, con cliente HTTP inyectado

Estado: propuesto (sesión 3)

## Contexto

La sesión 3 agrega un modelo real (Cloudflare Workers AI vía AI Gateway). Las pruebas, el
contrato y la evaluación deben seguir corriendo sin red ni cuota, y el token de Cloudflare es
secreto. Una falla del proveedor no debe verse como un error interno del producto.

## Decisión

- `GatewayModel` en `app/gateway.py` cumple la misma interfaz `LanguageModel.complete` que
  `FakeModel` (ADR 0002). Hay una instancia por nombre de modelo.
- Usa `httpx` con un cliente inyectado (`http_client`) y un tiempo de espera fijo.
- Cualquier falla (red, estado no 2xx, JSON inválido, sin `usage`) lanza `ModelUnavailable`;
  `/ask` responde `502 {"detail": "model unavailable", "request_id"}`.
- Con `MODEL_PROVIDER=gateway` faltar un `CF_*` impide arrancar. El token se guarda con
  `repr=False` y nunca va a mensajes de error ni al log.
- El prompt de sistema con el protocolo JSON vive en `gateway.py`; el modelo simulado no lo usa.

## Consecuencias

- El agente no cambia de protocolo ni conoce HTTP.
- Las pruebas usan `httpx.MockTransport`; nunca salen a la red.
- Un 502 cuenta en `error_rate` (es un 5xx) y queda en el log con su `request_id`.
