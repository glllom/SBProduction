"""
Плагин двустворчатых дверей (apps.production.engine.plugins.double_door).

Назначение модуля:
    Обрабатывает параметры деления полотен (par1 — пропорция, par2 — фиксированная
    ширина активной створки в см) и переводит позицию в режим двустворчатой двери.

Приоритет:
    priority = 10 — выполняется раньше остальных плагинов (в частности WoodEdgePlugin),
    так как толщина скрытого канта зависит от флага state.is_double (1.7 см вместо 1.0 см).
"""

from __future__ import annotations

from .registry import BaseCustomizerPlugin, register_customizer


@register_customizer('DOUBLE_DOOR', label='דלת כפולה (חלוקת כנפיים)')
class DoubleDoorPlugin(BaseCustomizerPlugin):
    """Разбирает параметры деления створок и активирует режим двустворчатой двери."""

    priority = 10

    def on_init(self, state, gc, cache) -> None:
        c = gc.customizer
        state.spec.is_double_door = True
        state.is_double = True

        try:
            par1_str = gc.par1 if gc.par1 not in (None, '') else c.par1_value
            state.double_door_par1 = float(par1_str) if par1_str else 0.5
        except (ValueError, TypeError):
            state.double_door_par1 = 0.5

        try:
            par2_str = gc.par2 if gc.par2 not in (None, '') else c.par2_value
            state.double_door_par2 = float(par2_str) if par2_str else 0.0
        except (ValueError, TypeError):
            state.double_door_par2 = 0.0
