# 0006 Trazas opcionales con LangSmith detrás de un Tracer

Estado: propuesto (sesión 2)

## Contexto

Las trazas de LangSmith ayudan a ver cada vuelta del agente, pero son un servicio externo:
el producto debe funcionar igual sin clave, no conectarse en pruebas y no enviar texto de
preguntas ni respuestas salvo que se pida. El agente no debe depender de LangSmith.

## Decisión

- Interfaz `Tracer` con `wrap(fn, name, run_type)` y `context(request_id)`. `NoopTracer`
  devuelve la función sin cambios; `LangSmithTracer` usa `langsmith.traceable` y
  `tracing_context` con `metadata={"request_id": ...}`.
- `build_tracer(settings)` elige `LangSmithTracer` solo si `LANGSMITH_TRACING=true` y existe
  `LANGSMITH_API_KEY`; `langsmith` se importa solo en ese caso.
- `Agent` recibe el tracer y envuelve `run` (`chain`), `model.complete` (`llm`) y cada
  herramienta (`tool`).
- `HIDE_INPUTS` y `HIDE_OUTPUTS` (por omisión `true`) se pasan al `Client` de LangSmith.
- La clave nunca se guarda en `Settings` ni se escribe en el log; la lee `langsmith`.

## Consecuencias

- Sin clave el producto no intenta conectarse y las pruebas usan `NoopTracer` o un doble.
- Cambiar de proveedor de trazas es escribir otro `Tracer`, sin tocar el agente.
- Con los valores por omisión las trazas muestran estructura, tiempos y metadatos, no texto.
- Se agrega `langsmith` a `requirements.txt`.
