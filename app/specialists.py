"""Especialistas del sistema multi-agente: ``directory`` y ``policy``.

Cada especialista es un ``Agent`` con su bucle con tope, sus herramientas y su
prompt. El modelo no se fija aquí: lo elige el enrutador de costo en cada
pregunta y se pasa a ``Agent.run``. ``ground_policy`` consulta en código la
política de la pregunta cuando el supervisor eligió ``policy`` por regla.
"""

from dataclasses import dataclass

from app.agent import TOOL_RESULT_PREFIX, Agent, directory_tools
from app.policies import SEARCH_POLICY_TOOL
from app.prompts import POLICY_PROMPT
from app.supervisor import DIRECTORY, POLICY


@dataclass(frozen=True)
class Grounding:
    """Consulta de política hecha en código antes de llamar al modelo.

    :param messages: Mensajes que van antes del historial y la pregunta
    :type messages: tuple[dict, ...]
    :param tool_calls: Herramientas ejecutadas en código, con sus argumentos
    :type tool_calls: tuple[dict, ...]
    """

    messages: tuple = ()
    tool_calls: tuple = ()

    @property
    def tools_used(self):
        """Nombres de las herramientas ejecutadas en código, en orden.

        :return: Herramientas
        :rtype: list[str]
        """
        return [call["tool"] for call in self.tool_calls]


def ground_policy(policies, question):
    """Consulta en código la política de la pregunta (supervisor ``rule:policy``).

    El texto es el mismo que devolvería ``search_policy`` y va como un mensaje
    ``user`` que empieza con ``TOOL_RESULT_PREFIX``, igual que los resultados
    de herramienta del bucle del agente: así el modelo ya no decide si
    consultar la política.

    :param policies: Libro de políticas
    :type policies: app.policies.PolicyBook
    :param question: Pregunta ya redactada por el guardián
    :type question: str
    :return: Mensaje con la política y la llamada registrada; vacío si la
        pregunta no trae palabra clave de ninguna política
    :rtype: Grounding
    """
    topic = policies.find_topic(question)
    if topic is None:
        return Grounding()
    text = policies.search_policy(topic)
    return Grounding(
        messages=({"role": "user", "content": TOOL_RESULT_PREFIX + text},),
        tool_calls=({"tool": SEARCH_POLICY_TOOL, "args": {"topic": topic}},),
    )


def build_specialists(directory, policies, max_steps, tracer=None):
    """Arma los dos especialistas.

    ``directory`` no lleva prompt propio: el modelo usa el de las sesiones
    anteriores, así una pregunta de directorio cuesta lo mismo que antes.

    :param directory: Directorio de empleados de solo lectura
    :type directory: app.directory.EmployeeDirectory
    :param policies: Libro de políticas
    :type policies: app.policies.PolicyBook
    :param max_steps: Tope de vueltas de cada especialista
    :type max_steps: int
    :param tracer: Tracer de las corridas; si falta no se traza nada
    :type tracer: app.tracing.NoopTracer or None
    :return: Especialistas por nombre
    :rtype: dict[str, app.agent.Agent]
    """
    return {
        DIRECTORY: Agent(
            tools=directory_tools(directory),
            max_steps=max_steps,
            tracer=tracer,
            name=DIRECTORY,
        ),
        POLICY: Agent(
            tools={SEARCH_POLICY_TOOL: policies.search_policy},
            max_steps=max_steps,
            tracer=tracer,
            name=POLICY,
            system_prompt=POLICY_PROMPT,
        ),
    }
