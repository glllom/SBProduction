"""
Драйвер станка ЧПУ SCM Accord — режим ручного проекта (apps.production.cnc.accord_custom).

Назначение модуля:
    Используется для нестандартных дверей, а также автоматически активируется
    для наклейки 2 (FINISHING), когда на группе заказа включён флаг פרט מיוחד
    (OrderItemsGroup.is_special_detail = True).

Формат QR-кода:
    C:\\Ww8\\PROJECTS\\<order_number>\\d<item_mark>.pgmx
"""

from __future__ import annotations

from .registry import BaseMachineDriver, MachineContext, register_machine


@register_machine('ACCORD_CUSTOM', label='Accord (פרויקט ידני)')
class AccordCustomDriver(BaseMachineDriver):
    """Драйвер прямого пути к индивидуальному файлу проекта Accord (.pgmx)."""

    PROJECTS_ROOT = r"C:\Ww8\PROJECTS"

    def build_qr_payload(self, ctx: MachineContext) -> str:
        """Возвращает прямой путь к индивидуальному файлу проекта двери."""
        mark = ctx.item_mark or '1'
        return f"{self.PROJECTS_ROOT}\\{ctx.order_number}\\d{mark}.pgmx"
