# 0014 Guardián de entrada y revisor de salida en código

Estado: propuesto (reto); actualizado con la adenda del punto 3 de `spec/05-reto.md` y con la
adenda 2 («Políticas ancladas al texto», corrección 2)

## Contexto

El asistente recibe texto libre del personal y responde con datos de RH. Hay que frenar el
prompt injection, evitar que datos personales (correo, teléfono, CURP, RFC, tarjeta, NSS)
lleguen al modelo, al log o a la traza, y no publicar respuestas que citen empleados que no
existen. Pedirle esto a otro modelo cuesta, es lento y no es determinista.

Hallazgo de producción del 2026-11-19: con el modelo real, a «Soy [EMAIL], ¿cuántos días de
vacaciones tengo?» el especialista `policy` no pidió `search_policy` y respondió «5 días»; la
política dice 12. `POLICY_PROMPT` ya pedía consultar la herramienta y no inventar datos: una
instrucción en el prompt no basta para que el modelo consulte.

## Decisión

- `app/guard.py` corre antes que cualquier modelo: frases de injection normalizadas en la
  pregunta y en los mensajes `user` del historial -> `400 request blocked by input policy`.
  Después redacta la PII con `app/pii.py` (expresiones regulares y Luhn) y la petición sigue.
- `app/reviewer.py` corre al final: redacta PII, reemplaza la respuesta si menciona un
  `EMP-dddd` que no está en el directorio **y que la persona no escribió en su pregunta**
  (un id inventado por el modelo); los ids se comparan sin distinguir mayúsculas contra la
  pregunta ya redactada por el guardián. Al final la recorta a `MAX_ANSWER_CHARS`.
- **La política se inyecta en código.** Con `rule:policy`, `AskPipeline._ground` llama a
  `ground_policy` (`app/specialists.py`), que pone el texto de `search_policy` como mensaje
  «Resultado de la herramienta: » antes de la primera llamada al modelo y registra
  `search_policy` en `tools_used` y en el `audit`. Por qué en código y no dejar que el modelo
  decida: el supervisor ya sabe el tema por la palabra clave, así que consultar es
  determinista, gratis y se puede probar; dejarlo al modelo depende de que obedezca el prompt,
  que es justo lo que falló en producción. De paso ahorra una vuelta al modelo (ver
  [costos](../costs.md)).
- **Regla de cifras.** Para respuestas de `policy`, `ground_in_policies` exige que cada cifra
  completa de la respuesta (`numbers`, `\d+`) aparezca en los textos de las políticas
  consultadas en la petición (`_policy_texts`, `PolicyBook.consulted_texts`). Si falta una, la
  respuesta se reemplaza por el primer texto consultado; si no hubo consulta, por
  `UNVERIFIED_POLICY_ANSWER`. Es la red de seguridad para lo que la inyección no cubre (ruta
  `model`, o un modelo que ignora el texto que recibió).
- Cada acción deja un `audit` con tipos y conteos, nunca valores (`output_blocked` con
  `reason: unknown_employee_id` o `ungrounded_policy_number`); los contadores van a
  `/metrics` en `security`.

## Consecuencias

- Controles deterministas, sin costo de tokens y con pruebas unitarias por regla
  (`tests/test_reviewer.py`) y de punta a punta del caso de producción
  (`tests/features/policy_grounding.feature`).
- Las listas de frases y patrones no cubren todo; se amplían con evidencia (`blocked_inputs`).
- Puede haber falsos positivos; el error es claro y se ve en la auditoría.
- Una persona que pregunta por un id inexistente (por ejemplo `EMP-9999`) recibe la respuesta
  de que no existe, como en la sesión 1, y no el mensaje de verificación. La primera versión
  de esta decisión bloqueaba también ese caso y rompía la respuesta de la sesión 1.
- La regla de cifras solo ve dígitos: «cinco días» o una cifra de la política usada fuera de
  lugar pasan. Una cifra de la pregunta que no está en la política hace que se responda con el
  texto completo de la política (falso positivo seguro).
