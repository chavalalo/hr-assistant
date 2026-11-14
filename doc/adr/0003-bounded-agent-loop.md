# 0003. Un solo agente con bucle con tope y protocolo JSON

Estado: propuesto

## Contexto

El agente alterna entre pedir herramientas y responder. Sin un límite, un modelo que siempre pide
herramientas haría un bucle infinito, con costo y latencia sin control.

## Decisión

- Un solo agente con dos herramientas de solo lectura: `get_employee` y `search_by_department`.
- El modelo responde un único objeto JSON: `{"tool", "args"}` o `{"answer"}`.
- Cada llamada al modelo es una vuelta; `steps` es el número de llamadas hechas.
- El resultado de una herramienta vuelve como mensaje `user` que empieza con
  `Resultado de la herramienta: ` (JSON con `ensure_ascii=False`).
- Al llegar a `AGENT_MAX_STEPS` sin `answer`, la respuesta es exactamente
  `No pude completar la respuesta. Intenta con una pregunta más concreta.`
- JSON inválido, herramienta desconocida o argumentos malos se devuelven al modelo como resultado
  de error; no lanzan excepción a la API.

## Consecuencias

- Cada pregunta tiene un costo máximo conocido (`AGENT_MAX_STEPS` llamadas).
- Preguntas que necesiten más vueltas que el tope reciben el mensaje de tope; se ajusta por
  configuración.
- Agregar herramientas es registrar una función más en el diccionario del agente.
