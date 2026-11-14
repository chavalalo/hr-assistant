"""Errores compartidos por la configuración y los módulos que la validan."""


class ConfigError(ValueError):
    """Error de configuración: algún valor de entorno no es válido."""
