# 0014 Guardián de entrada y revisor de salida en código

Estado: propuesto (reto); actualizado con la adenda del punto 3 de `spec/05-reto.md`

## Contexto

El asistente recibe texto libre del personal y responde con datos de RH. Hay que frenar el
prompt injection, evitar que datos personales (correo, teléfono, CURP, RFC, tarjeta, NSS)
lleguen al modelo, al log o a la traza, y no publicar respuestas que citen empleados que no
existen. Pedirle esto a otro modelo cuesta, es lento y no es determinista.

## Decisión

- `app/guard.py` corre antes que cualquier modelo: frases de injection normalizadas en la
  pregunta y en los mensajes `user` del historial -> `400 request blocked by input policy`.
  Después redacta la PII con `app/pii.py` (expresiones regulares y Luhn) y la petición sigue.
- `app/reviewer.py` corre al final: redacta PII, reemplaza la respuesta si menciona un
  `EMP-dddd` que no está en el directorio **y que la persona no escribió en su pregunta**
  (un id inventado por el modelo); los ids se comparan sin distinguir mayúsculas contra la
  pregunta ya redactada por el guardián. Al final la recorta a `MAX_ANSWER_CHARS`.
- Cada acción deja un `audit` con tipos y conteos, nunca valores; los contadores van a
  `/metrics` en `security`.

## Consecuencias

- Controles deterministas, sin costo de tokens y con pruebas unitarias por regla.
- Las listas de frases y patrones no cubren todo; se amplían con evidencia (`blocked_inputs`).
- Puede haber falsos positivos; el error es claro y se ve en la auditoría.
- Una persona que pregunta por un id inexistente (por ejemplo `EMP-9999`) recibe la respuesta
  de que no existe, como en la sesión 1, y no el mensaje de verificación. La primera versión
  de esta decisión bloqueaba también ese caso y rompía la respuesta de la sesión 1.
