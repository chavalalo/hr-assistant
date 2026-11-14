# 0008 Enrutamiento por regla y ventana de historial

Estado: propuesto (sesión 3)

## Contexto

La mayoría de las preguntas (un empleado, un departamento) las resuelve un modelo pequeño y
barato; las que piden comparar, resumir o explicar necesitan uno capaz. Además, el historial que
manda el navegador crece con cada vuelta y cada token de entrada cuesta.

## Decisión

- `app/levers.py` tiene dos funciones puras: `choose_model` y `trim_history`.
- `choose_model` es una regla en código, no otro modelo: grande si `ROUTING=false`, si la
  pregunta pasa de `ROUTER_MAX_CHARS` o si una palabra clave aparece al inicio de una palabra
  (sin acentos ni mayúsculas). Devuelve el modelo y el motivo (`route`).
- El modelo se elige una vez por pregunta y se usa en todas las vueltas del agente.
- `trim_history` deja los últimos `HISTORY_WINDOW` mensajes del cliente; 0 significa ninguno.

## Consecuencias

- Enrutar no cuesta tokens ni latencia y es fácil de probar y de explicar (`route`).
- Una regla puede equivocarse; la evaluación (ADR 0009) decide si la palanca se queda.
- La API sigue sin estado (ADR 0001): el cliente manda todo y el servidor solo recorta.
