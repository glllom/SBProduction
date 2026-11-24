"""
Утилиты автоматического обнаружения плагинов и модулей расширения (pkgutil).

Назначение модуля:
    Обеспечивает принцип "положил .py файл в нужную папку — и система сама его увидела".
    Используется всеми реестрами производства:
        - apps.production.cnc           (драйверы станков ЧПУ)
        - apps.production.reports       (обработчики печатных отчётов станций)
        - apps.production.engine.plugins (плагины нестандартных кастомизаторов)

Особенности:
    - Повторные вызовы для одного и того же пакета безопасны и идемпотентны
      (уже просканированные пакеты кешируются в _DISCOVERED_PACKAGES).
    - Служебные модули (начинающиеся с '_' и базовый 'registry.py') пропускаются.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Set

# Кэш уже просканированных пакетов, чтобы не обходить файловую систему повторно
_DISCOVERED_PACKAGES: Set[str] = set()

# Имена служебных модулей, которые не являются плагинами
_SKIP_MODULE_NAMES = frozenset({'registry', 'base', 'common'})


def autodiscover_package(package_path: str) -> None:
    """
    Импортирует все модули первого уровня внутри указанного Python-пакета,
    чтобы выполнились их декораторы регистрации (@register_machine, @register_report и т.д.).

    Args:
        package_path: Полный путь пакета, например 'apps.production.cnc'.
    """
    if package_path in _DISCOVERED_PACKAGES:
        return

    package = importlib.import_module(package_path)
    package_paths = getattr(package, '__path__', None)
    if not package_paths:
        _DISCOVERED_PACKAGES.add(package_path)
        return

    # Помечаем пакет до обхода, чтобы защититься от рекурсивного повторного входа
    _DISCOVERED_PACKAGES.add(package_path)

    for _, module_name, _ in pkgutil.iter_modules(package_paths):
        if module_name.startswith('_') or module_name in _SKIP_MODULE_NAMES:
            continue
        importlib.import_module(f"{package_path}.{module_name}")
