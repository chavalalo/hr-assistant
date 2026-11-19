"""Especialistas del sistema multi-agente: ``directory`` y ``policy``.

Cada especialista es un ``Agent`` con su bucle con tope, sus herramientas y su
prompt. El modelo no se fija aquí: lo elige el enrutador de costo en cada
pregunta y se pasa a ``Agent.run``.
"""

from app.agent import Agent, directory_tools
from app.prompts import POLICY_PROMPT
from app.supervisor import DIRECTORY, POLICY


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
            tools={"search_policy": policies.search_policy},
            max_steps=max_steps,
            tracer=tracer,
            name=POLICY,
            system_prompt=POLICY_PROMPT,
        ),
    }
