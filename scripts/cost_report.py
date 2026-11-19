"""Reporte de costos a partir del log JSON (spec/05-reto.md, punto 9).

Uso::

    python scripts/cost_report.py uvicorn.log
    python scripts/cost_report.py < uvicorn.log

Lee las líneas del log, ignora las que no son JSON (por ejemplo las de uvicorn)
y resume los eventos ``agent_run``: peticiones, costo y tokens por cliente, por
especialista y por modelo, más la tasa de aciertos de la caché de respuestas.
Solo usa la biblioteca estándar.

Códigos de salida: 0 si pudo leer el log, 2 si el archivo no existe.
"""

import argparse
import json
import sys
from dataclasses import dataclass

AGENT_RUN_EVENT = "agent_run"
# Valor cuando una línea vieja no trae el campo (por ejemplo sin ``specialist``)
UNKNOWN = "desconocido"
GROUPS = (
    ("Por cliente", "client"),
    ("Por especialista", "specialist"),
    ("Por modelo", "model"),
)
NAME_WIDTH = 42


@dataclass
class Totals:
    """Acumulado de un grupo de corridas.

    :param requests: Corridas contadas
    :type requests: int
    :param cost_usd: Costo total en USD
    :type cost_usd: float
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    """

    requests: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, record):
        """Suma una corrida ``agent_run``.

        :param record: Línea del log ya convertida
        :type record: dict
        """
        self.requests += 1
        self.cost_usd += _number(record.get("cost_usd"))
        self.input_tokens += int(_number(record.get("input_tokens")))
        self.output_tokens += int(_number(record.get("output_tokens")))


def _number(value):
    """Convierte un campo numérico del log; lo que no es número vale 0.

    :param value: Valor del campo
    :type value: object
    :return: El número o 0
    :rtype: float
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def read_agent_runs(lines):
    """Extrae los eventos ``agent_run`` de las líneas del log.

    :param lines: Líneas del log
    :type lines: collections.abc.Iterable[str]
    :return: Eventos ``agent_run`` en el orden del log
    :rtype: list[dict]
    """
    runs = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == AGENT_RUN_EVENT:
            runs.append(record)
    return runs


def summarize(runs):
    """Agrupa las corridas por cliente, especialista y modelo.

    :param runs: Eventos ``agent_run``
    :type runs: list[dict]
    :return: Total general, totales por campo y nombre, y respuestas de caché
    :rtype: tuple[Totals, dict[str, dict[str, Totals]], int]
    """
    overall = Totals()
    groups = {field: {} for _, field in GROUPS}
    cache_hits = 0
    for record in runs:
        overall.add(record)
        if record.get("cached") is True:
            cache_hits += 1
        for field, totals in groups.items():
            name = str(record.get(field) or UNKNOWN)
            totals.setdefault(name, Totals()).add(record)
    return overall, groups, cache_hits


def print_group(title, totals):
    """Imprime la tabla de un grupo, de mayor a menor costo.

    :param title: Título de la tabla
    :type title: str
    :param totals: Totales por nombre
    :type totals: dict[str, Totals]
    """
    print(f"\n{title}")
    header = "nombre".ljust(NAME_WIDTH)
    print(f"  {header} {'peticiones':>10} {'costo_usd':>12} {'in':>8} {'out':>8}")
    ordered = sorted(totals.items(), key=lambda item: (-item[1].cost_usd, item[0]))
    for name, item in ordered:
        print(
            f"  {name[:NAME_WIDTH].ljust(NAME_WIDTH)} {item.requests:>10} "
            f"{item.cost_usd:>12.6f} {item.input_tokens:>8} {item.output_tokens:>8}"
        )


def print_report(runs):
    """Imprime el reporte completo.

    :param runs: Eventos ``agent_run``
    :type runs: list[dict]
    """
    overall, groups, cache_hits = summarize(runs)
    hit_rate = cache_hits / overall.requests if overall.requests else 0.0
    print(f"peticiones: {overall.requests}")
    print(f"costo_total_usd: {overall.cost_usd:.6f}")
    if overall.requests:
        print(f"costo_por_peticion_usd: {overall.cost_usd / overall.requests:.6f}")
    print(f"tokens: entrada {overall.input_tokens}, salida {overall.output_tokens}")
    print(f"cache: {cache_hits} de {overall.requests} (tasa {hit_rate:.1%})")
    for title, field in GROUPS:
        print_group(title, groups[field])


def main(args):
    """Lee el log del archivo o de la entrada estándar e imprime el reporte.

    :param args: Argumentos de la línea de comandos sin el nombre del programa
    :type args: list[str]
    :return: 0 si pudo leer el log, 2 si el archivo no existe
    :rtype: int
    """
    parser = argparse.ArgumentParser(
        description="Resume costo, tokens y caché desde los eventos agent_run."
    )
    parser.add_argument(
        "log", nargs="?", help="archivo del log; sin él se lee la entrada estándar"
    )
    options = parser.parse_args(args)
    if options.log is None:
        print_report(read_agent_runs(sys.stdin))
        return 0
    try:
        with open(options.log, encoding="utf-8", errors="replace") as stream:
            runs = read_agent_runs(stream)
    except OSError as error:
        print(f"No se pudo leer el log ({type(error).__name__})")
        return 2
    print_report(runs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
