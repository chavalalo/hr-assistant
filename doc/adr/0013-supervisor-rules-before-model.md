# 0013 Supervisor con reglas antes que modelo

Estado: propuesto (reto)

## Contexto

El producto pasa de un agente a dos especialistas (`directory` y `policy`). Algo tiene que
elegir cuál responde. Preguntar siempre a un modelo suma una llamada, tokens y latencia a cada
pregunta, y la mayoría trae una señal clara: un id `EMP-dddd`, un departamento o una palabra
clave de `data/policies.json`.

## Decisión

- `app/supervisor.py` decide primero con reglas en código, en este orden: id de empleado
  (`rule:employee`), departamento existente (`rule:department`), palabra clave de política
  (`rule:policy`), sin acentos ni mayúsculas y sobre la pregunta ya redactada.
- Solo si ninguna regla aplica llama a `MODEL_SMALL` con `SUPERVISOR_PROMPT` y sin historial.
  Respuesta inválida o modelo caído -> `directory` con `model_invalid`.
- El motivo sale en `supervisor_route`; esa llamada suma tokens y costo a la respuesta.
- `ROUTING` (ADR 0008) sigue eligiendo el modelo del especialista.

## Consecuencias

- Las preguntas con regla cuestan lo mismo que en la sesión 4; la evaluación no empeora.
- La decisión es explicable y se prueba sin red; `supervisor.rule` y `supervisor.model` en
  `/metrics` muestran cuánto decide cada uno.
- Una regla puede elegir mal en preguntas mixtas; la precedencia está fija y documentada.
