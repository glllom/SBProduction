"""
Пакет драйверов станков ЧПУ (apps.production.cnc).

Экспортирует базовый контракт драйвера, реестр и инструменты потоковой генерации
библиотек макросов. Все драйверы в этой папке (файлы .py и подпакеты) подгружаются
автоматически при старте Django.
"""

from apps.production.library import (
    LibraryBuildResult,
    LibraryBuildScope,
    MachineLibraryService,
    render_cnc_template,
    render_cnc_template_file,
    safe_path_segment,
)
from .registry import BaseMachineDriver, MachineContext, MachineRegistry, register_machine

__all__ = [
    'BaseMachineDriver',
    'LibraryBuildResult',
    'LibraryBuildScope',
    'MachineContext',
    'MachineLibraryService',
    'MachineRegistry',
    'register_machine',
    'render_cnc_template',
    'render_cnc_template_file',
    'safe_path_segment',
]
