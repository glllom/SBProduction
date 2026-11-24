"""
Драйвер станка ЧПУ Essepigi (apps.production.cnc.essepigi).

Формат QR-кодов:
    - Наклейки 0 (PRE_ROUGHING) и 1 (ROUGHING) — периметральная обработка:
        PRG=<cnc_program>;EDGE_SHAPE=<0|1>;L=<H_mm>;W=<W_mm>;EDGE=<edge_type>
    - Наклейка 2 (FINISHING) — врезка фурнитуры, замков и гравировка:
        CMD=LOCKS;L=<H_mm>;W=<W_mm>;EDGE=<edge_type>;LOCK_H=<h>;HINGES=<h1,h2,...>[;ENGRAVE=<icon>;P1=...]
"""

from __future__ import annotations

from apps.production.models import DoorLabel
from .registry import BaseMachineDriver, MachineContext, register_machine


@register_machine('ESSEPIGI', label='Essepigi')
class EssepigiDriver(BaseMachineDriver):
    """Драйвер формирования командных QR-строк для обрабатывающего центра Essepigi."""

    def build_qr_payload(self, ctx: MachineContext) -> str:
        """Собирает QR-строку в синтаксисе Essepigi в зависимости от типа операции."""
        edge = ctx.edge_type or 'STANDARD'
        edge_shape_flag = int(ctx.edge_shape)

        # Операции периметральной обрезки (наклейки 0 и 1)
        if ctx.label_type in (DoorLabel.LabelType.PRE_ROUGHING, DoorLabel.LabelType.ROUGHING):
            return (
                f"PRG={ctx.cnc_program};"
                f"EDGE_SHAPE={edge_shape_flag};"
                f"L={ctx.height_mm:g};"
                f"W={ctx.width_mm:g};"
                f"EDGE={edge}"
            )

        # Финишная обработка: замок, петли и (опционально) фрезеровка фасада (наклейка 2)
        lock_h = ctx.lock_height or 0
        hinges_str = ",".join(str(h) for h in ctx.hinge_heights)

        payload = (
            f"CMD=LOCKS;"
            f"L={ctx.height_mm:g};"
            f"W={ctx.width_mm:g};"
            f"EDGE={edge};"
            f"LOCK_H={lock_h:g};"
            f"HINGES={hinges_str}"
        )

        icon = (ctx.engraving_data or {}).get('icon_filename')
        if icon:
            payload += f";ENGRAVE={icon}"
            for i in range(1, 6):
                val = ctx.engraving_data.get(f'p{i}')
                if val is not None:
                    payload += f";P{i}={val}"

        return payload
