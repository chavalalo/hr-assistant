# 0015 Caché de respuestas en proceso

Estado: propuesto (reto)

## Contexto

Muchas personas hacen las mismas preguntas (vacaciones, horario, un empleado). La caché de AI
Gateway (sesión 3) solo ahorra si el cuerpo de la petición es idéntico y no evita el supervisor
ni el bucle del agente. Se busca una palanca que baje el costo sin bajar la calidad, medida
contra la línea base en `verification evaluate`.

## Decisión

- `app/cache.py` guarda en memoria del proceso la respuesta final por pregunta normalizada
  (minúsculas, sin acentos, espacios colapsados), con TTL `ANSWER_CACHE_TTL_SECONDS` y tope
  `ANSWER_CACHE_MAX_ENTRIES` (sale la más vieja), protegida con un candado.
- Solo se consulta y se guarda sin historial, sin PII y con una respuesta sana (sin bloqueo del
  revisor ni respaldo). Un acierto responde con `cached: true`, costo y tokens en 0 y `agents:
  ["guard", "cache"]`; el guardián siempre corre antes.
- Apagada por omisión (`0`); en `render.yaml` va en `300`.

## Consecuencias

- Las preguntas repetidas cuestan 0 y responden en milisegundos; `cache.hit_rate` lo muestra.
- Una respuesta puede tener hasta 300 s de antigüedad; los datos son de solo lectura.
- Es por proceso: con varios workers o reinicios se pierde (un solo worker, ADR 0005).
- Se comparte entre clientes porque todos ven los mismos datos; si eso cambia, la llave debe
  incluir al cliente.
