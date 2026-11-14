# 0009 Costo por respuesta con tabla de precios y modelos simulados con precio

Estado: propuesto (sesión 3)

## Contexto

Cada palanca de costo debe medirse y descartarse si baja la calidad. Medir con el modelo real
gasta cuota y no es repetible; medir sin precio no dice nada.

## Decisión

- `app/costs.py` carga `data/model_prices.json` (copia de `spec/`, USD por millón de tokens) y
  calcula el costo de cada llamada no cacheada con el precio del modelo elegido.
- Una llamada con `cf-aig-cache-status: HIT` cuenta en `cached_calls` y cuesta 0.
- `/ask` devuelve `model`, `route`, `cached_calls` y `cost_usd`; `/metrics` acumula `cost_usd`.
- Con `MODEL_PROVIDER=fake` hay dos modelos simulados idénticos con los nombres de
  `MODEL_SMALL` y `MODEL_LARGE`; su costo sale del precio de su nombre.
- Si un modelo configurado no tiene precio, el producto no arranca.
- `cost_usd` se redondea a 10 decimales para no volver cero los costos pequeños.

## Consecuencias

- `verification evaluate` compara línea base contra palancas sin red y de forma repetible.
- Con el simulado la calidad no depende del modelo; la evaluación real de calidad requiere el
  gateway y queda fuera de las verificaciones automáticas.
- Los precios cambian: hay que actualizar el JSON; el código no lleva precios.
