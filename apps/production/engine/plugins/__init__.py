"""
Пакет плагинов нестандартных кастомизаторов (apps.production.engine.plugins).

Экспортирует базовый класс BaseCustomizerPlugin, реестр CustomizerPluginRegistry
и декоратор register_customizer. Все плагины в этой папке подгружаются автоматически.
"""

from .registry import BaseCustomizerPlugin, CustomizerPluginRegistry, register_customizer

__all__ = [
    'BaseCustomizerPlugin',
    'CustomizerPluginRegistry',
    'register_customizer',
]
