# 0001. API sin estado con historial en el cliente

Estado: propuesto

## Contexto

El HR Assistant debe escalar corriendo más copias de la API. Si el servidor guarda la
conversación, cada copia tendría un historial distinto y haría falta afinidad de sesión o una
base de datos compartida.

## Decisión

- La API no guarda nada entre peticiones: sin variables globales mutables, sin sesiones, sin caché
  por usuario.
- El navegador guarda el historial y lo manda en cada `POST /ask` como `history`.
- La API valida ese historial (roles solo `user` o `assistant`) y lo usa solo durante la petición.
- El directorio de empleados se carga al arrancar y es de solo lectura; no cuenta como estado.

## Consecuencias

- Cualquier copia puede atender cualquier petición; escalar es correr más procesos.
- Las peticiones crecen con la conversación; si llega a ser un problema se agrega un tope de
  historial por configuración.
- El cliente puede alterar su historial: se trata como dato no confiable y se valida.
