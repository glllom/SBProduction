"""
Плагин подмены наличника (apps.production.engine.plugins.casing).

Назначение модуля:
    При активном кастомизаторе CASING заменяет базовый материал слота BOM.casing
    на его альтернативный материал (Material.outward_substitute) до сборки SpecBOMItem.
"""

from __future__ import annotations

import copy

from .registry import BaseCustomizerPlugin, register_customizer


@register_customizer('CASING', label='החלפת הלבשה (שימוש בחומר חלופי)')
class CasingSubstitutePlugin(BaseCustomizerPlugin):
    """Переключает материал наличника в effective_bom на outward_substitute."""

    priority = 50

    def on_before_bom(self, state, gc, cache) -> None:
        if not state.effective_bom:
            return
        current_casing = getattr(state.effective_bom, 'casing', None)
        if not current_casing:
            return
        substitute = getattr(current_casing, 'outward_substitute', None)
        if not substitute:
            return

        patched = copy.copy(state.effective_bom)
        patched.casing = substitute
        state.effective_bom = patched
