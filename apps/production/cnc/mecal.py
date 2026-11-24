"""
Драйвер станка Mecal для алюминиевых профилей (apps.production.cnc.mecal).

Назначение модуля:
    Выносит генерацию XML-файлов (hinges.xml, lock.xml) из ProductionDataService
    в изолированный драйвер станка. В будущем вся специфика протокола Mecal
    (координаты отверстий, пазы, фрезы) развивается только в этом файле.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .registry import BaseMachineDriver, MachineContext, register_machine


@register_machine('MECAL', label='Mecal (אלומיניום)')
class MecalDriver(BaseMachineDriver):
    """Драйвер генерации XML-файлов обработки алюминиевых коробок и полотен для Mecal."""

    def build_qr_payload(self, ctx: MachineContext) -> str:
        """Возвращает идентификатор заказа и позиции (Mecal работает по файлам XML)."""
        return f"MECAL;{ctx.order_number};d{ctx.item_mark}"

    def generate_files(self, order, specs: List[Any]) -> Dict[str, bytes]:
        """
        Формирует словарь XML-файлов в структуре:
            frames/frame_<mark>/hinges.xml, frames/frame_<mark>/lock.xml
            doors/door_<mark>/hinges.xml,   doors/door_<mark>/lock.xml
        """
        files: Dict[str, bytes] = {}

        for spec in specs:
            mark = getattr(spec, 'mark', '') or str(getattr(spec, 'item_id', ''))

            if getattr(spec, 'has_frame', False):
                prefix = f"frames/frame_{mark}"
                files[f"{prefix}/hinges.xml"] = self._render_xml('hinges', spec, 'frame').encode('utf-8')
                files[f"{prefix}/lock.xml"] = self._render_xml('lock', spec, 'frame').encode('utf-8')

            if getattr(spec, 'has_door', False):
                prefix = f"doors/door_{mark}"
                files[f"{prefix}/hinges.xml"] = self._render_xml('hinges', spec, 'door').encode('utf-8')
                files[f"{prefix}/lock.xml"] = self._render_xml('lock', spec, 'door').encode('utf-8')

        return files

    @staticmethod
    def _render_xml(root_tag: str, spec: Any, item_type: str) -> str:
        """Генерирует XML-документ для петель или замка (заготовка под будущие правила Mecal)."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<{root_tag}>\n'
            '  <status>placeholder</status>\n'
            f'  <item_id>{spec.item_id}{item_type}</item_id>\n'
            f'</{root_tag}>'
        )
