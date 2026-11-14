# 0012 Contenedor, CI en cuatro etapas y Render con checksPass

Estado: propuesto (sesión 4)

## Contexto

Publicar debe ser repetible y solo con código que pasó las mismas compuertas que en la fábrica.
Los ingenieros quieren ver cada etapa, y los secretos no pueden vivir en el repositorio.

## Decisión

- Imagen `python:3.12-slim` con usuario sin privilegios, un solo worker de uvicorn y
  `--port ${PORT:-8000}` por `sh -c`; `.dockerignore` deja fuera `.env`, pruebas y cachés.
- `.github/workflows/ci.yml` con `style` -> `unit` -> `e2e` -> `docker`, encadenados con
  `needs`, en cada push y pull request; usan los mismos comandos que `verification` y el modelo
  simulado con una clave de ejemplo.
- `render.yaml` (Blueprint) con un servicio llamado como el repositorio, `runtime: docker`,
  `plan: free`, `healthCheckPath: /health` y `autoDeployTrigger: checksPass`. Los secretos van
  con `sync: false` y se escriben en Render; `LANGSMITH_API_KEY` no se declara.
- Publicar (`scripts/publish.py`) exige la aprobación de una persona; después,
  `scripts/smoke.py` y `verification production` comprueban el servicio vivo.

## Consecuencias

- Un commit con el CI en rojo nunca se despliega; la causa se ve en la pestaña Actions.
- La imagen incluye dependencias de prueba porque hay un solo `requirements.txt`; es más
  grande, a cambio de una sola fuente de versiones.
- El plan gratuito duerme: la primera petición tarda hasta un minuto.
