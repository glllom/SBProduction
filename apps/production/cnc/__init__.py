"""
Пакет драйверов станков ЧПУ (apps.production.cnc).

Экспортирует базовый контракт и реестр для работы из генератора наклеек,
экспорта файлов и админки. Все драйверы в этой папке подгружаются автоматически.
"""

from .registry import BaseMachineDriver, MachineContext, MachineRegistry, register_machine

__all__ = [
    'BaseMachineDriver',
    'MachineContext',
    'MachineRegistry',
    'register_machine',
]
