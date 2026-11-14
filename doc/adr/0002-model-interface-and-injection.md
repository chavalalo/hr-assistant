# 0002. Modelo detrás de una interfaz e inyección de dependencias

Estado: propuesto

## Contexto

Hoy solo existe un modelo simulado, pero en sesiones futuras se conectará un modelo real. Las
pruebas deben correr sin red, sin costo y de forma determinista.

## Decisión

- `llm.py` define la interfaz `LanguageModel` con un solo método
  `complete(messages) -> Completion(text, input_tokens, output_tokens)`.
- `FakeModel` la implementa con las reglas de la especificación y recibe los departamentos por
  constructor (no depende de `directory.py`).
- `build_model(settings, departments)` elige el proveedor según `MODEL_PROVIDER`; hoy solo
  acepta `fake`.
- `create_app(settings, model, directory)` recibe sus dependencias; si no se pasan, las construye
  a partir del entorno. Las pruebas inyectan las suyas.

## Consecuencias

- Agregar un modelo real es una clase nueva y una rama en `build_model`; el agente no cambia.
- Las pruebas no necesitan red ni variables de entorno.
- Un proveedor real deberá devolver el mismo protocolo JSON; si no, el agente lo trata como
  respuesta inválida.
