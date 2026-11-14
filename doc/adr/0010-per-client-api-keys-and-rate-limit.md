# 0010 Clave por cliente y límite de peticiones en memoria

Estado: propuesto (sesión 4)

## Contexto

Al publicar, cualquiera con la URL podría gastar la cuota del modelo. Hace falta saber quién
pregunta, cortar a quien abusa y no filtrar nunca una clave. El servicio corre en un solo
proceso en Render y ya guarda sus métricas en memoria (ADR 0005).

## Decisión

- `API_KEYS` (`cliente:clave,...`) se valida al arrancar en `app/auth.py`; un error dice la
  posición y el largo de la entrada, nunca su valor, y se lanza sin la excepción original.
- Una dependencia de FastAPI protege `/ask` y `/metrics`: compara `X-API-Key` con
  `hmac.compare_digest` contra todas las claves y deja el nombre del cliente en la petición.
  `/`, `/health`, `/docs` y `/openapi.json` siguen públicos.
- Después de la clave, `RateLimiter` aplica una ventana deslizante de 60 s por cliente con el
  reloj inyectado; al pasarse responde 429 con `Retry-After`.
- El log, la auditoría y la traza llevan `client`; la clave no sale del módulo de autenticación.

## Consecuencias

- Se puede auditar por cliente y revocar una clave cambiando una variable en Render.
- El límite vale por proceso: con varios workers o instancias se multiplica. Se mantiene un
  solo worker; un límite compartido requeriría un almacén externo.
- Las peticiones sin clave no se limitan; se mitiga con claves largas en producción y el evento
  `auth_rejected`.
- Las pruebas deben mandar una clave: las fixtures la ponen por omisión.
