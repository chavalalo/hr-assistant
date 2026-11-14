# 0011 Compliance como código: el producto se niega a arrancar

Estado: propuesto (sesión 4)

## Contexto

Las reglas de producción (modelo real, claves fuertes, trazas sin datos) se olvidan si viven
solo en un documento. Un servicio mal configurado que arranca puede responder con datos
inventados o mandar datos personales a un tercero antes de que alguien lo note.

## Decisión

- `app/compliance.py` define `violations(settings)`, una función pura con las tres reglas de
  `ENVIRONMENT=production`, y `enforce(settings)`, que lanza `ConfigError` con los nombres de
  las reglas rotas y sin valores.
- `create_app` llama `enforce`, así que `import app.main` falla y Render marca el despliegue
  como fallido en lugar de servir.
- La regla de trazas usa lo pedido (`LANGSMITH_TRACING=true`), no solo si hay clave.
- `doc/compliance-checklist.md` enlaza cada regla con su código y su prueba.

## Consecuencias

- Una configuración insegura no llega a recibir tráfico; el error se ve en el log de Render.
- En desarrollo nada cambia: las pruebas y la fábrica usan `development`.
- Agregar una regla es agregar una función y su prueba, y una fila en la tabla.
