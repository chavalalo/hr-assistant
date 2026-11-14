"""Precios por modelo y costo de una respuesta en USD.

Los precios vienen de ``data/model_prices.json`` en USD por millón de tokens.
Las llamadas que el gateway respondió desde su caché no cuestan.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

TOKENS_PER_PRICE_UNIT = 1_000_000
COST_DECIMALS = 10


@dataclass(frozen=True)
class ModelPrice:
    """Precio de un modelo en USD por millón de tokens.

    :param input_usd: Precio de los tokens de entrada
    :type input_usd: float
    :param output_usd: Precio de los tokens de salida
    :type output_usd: float
    """

    input_usd: float
    output_usd: float


def _parse_price(model, raw):
    """Convierte la entrada del archivo de precios en un ``ModelPrice``.

    :param model: Nombre del modelo, para el mensaje de error
    :type model: str
    :param raw: Objeto con ``input`` y ``output``
    :type raw: dict
    :return: Precio validado
    :rtype: ModelPrice
    :raises ValueError: Si falta un precio o es negativo
    """
    try:
        price = ModelPrice(
            input_usd=float(raw["input"]), output_usd=float(raw["output"])
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid price for model {model!r}") from error
    if price.input_usd < 0 or price.output_usd < 0:
        raise ValueError(f"negative price for model {model!r}")
    return price


class PriceTable:
    """Tabla inmutable de precios por nombre de modelo.

    :param prices: Precio de cada modelo
    :type prices: Mapping[str, ModelPrice]
    """

    def __init__(self, prices):
        self._prices = MappingProxyType(dict(prices))

    @classmethod
    def load(cls, path):
        """Lee la tabla de precios de un archivo JSON.

        :param path: Ruta al archivo con la llave ``models``
        :type path: str or pathlib.Path
        :return: Tabla de precios
        :rtype: PriceTable
        :raises OSError: Si el archivo no se puede leer
        :raises ValueError: Si el archivo no tiene el formato esperado
        """
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, dict):
            raise ValueError("the prices file must have a 'models' object")
        return cls({name: _parse_price(name, raw) for name, raw in models.items()})

    def __contains__(self, model):
        """Indica si el modelo tiene precio.

        :param model: Nombre del modelo
        :type model: str
        :return: ``True`` si el modelo está en la tabla
        :rtype: bool
        """
        return model in self._prices

    def price(self, model):
        """Devuelve el precio de un modelo.

        :param model: Nombre del modelo
        :type model: str
        :return: Precio del modelo
        :rtype: ModelPrice
        :raises KeyError: Si el modelo no tiene precio
        """
        try:
            return self._prices[model]
        except KeyError:
            raise KeyError(f"no price for model {model!r}") from None

    def cost(self, model, completions):
        """Calcula el costo en USD de las llamadas no cacheadas de una respuesta.

        Se redondea a 10 decimales: con pocas palabras el costo es del orden de
        una millonésima de dólar y no debe quedar en cero.

        :param model: Modelo cuyo precio se aplica
        :type model: str
        :param completions: Llamadas al modelo de una respuesta
        :type completions: Iterable[app.llm.Completion]
        :return: Costo en USD
        :rtype: float
        :raises KeyError: Si el modelo no tiene precio
        """
        price = self.price(model)
        total = sum(
            completion.input_tokens * price.input_usd
            + completion.output_tokens * price.output_usd
            for completion in completions
            if not completion.cached
        )
        return round(total / TOKENS_PER_PRICE_UNIT, COST_DECIMALS)
