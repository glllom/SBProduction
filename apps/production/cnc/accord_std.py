"""
Драйвер станка ЧПУ SCM Accord — библиотечный режим (apps.production.cnc.accord_std).

Формат QR-кода (разделитель '|'):
    <путь_к_программе.pgmx>|OP=<0|1|2>|EDGE_SHAPE=<0|1>|L=<H_mm>|W=<W_mm>|lock=<h>|h1=...|h2=...[|engrave=<icon>|p1=...]

Путь к программе:
    - Если задан cnc_program: C:\\Ww8\\PRG\\ROUTING\\<cnc_program>.pgmx
    - Иначе базовый шаблон:   C:\\Ww8\\PRG\\MODELS\\STD_DOOR.pgmx
"""

from __future__ import annotations

from .registry import BaseMachineDriver, MachineContext, register_machine


@register_machine('ACCORD_STD', label='Accord (ספרייה)')
class AccordStandardDriver(BaseMachineDriver):
    """Драйвер библиотечных параметрических макросов WoodWOP / Maestro для SCM Accord."""

    DEFAULT_MODEL_PATH = r"C:\Ww8\PRG\MODELS\STD_DOOR.pgmx"
    ROUTING_DIR = r"C:\Ww8\PRG\ROUTING"

    def build_qr_payload(self, ctx: MachineContext) -> str:
        """Формирует параметрическую строку запуска библиотечного макроса Accord."""
        prog_path = (
            f"{self.ROUTING_DIR}\\{ctx.cnc_program}.pgmx"
            if ctx.cnc_program
            else self.DEFAULT_MODEL_PATH
        )
        lock_h = ctx.lock_height or 0

        parts = [
            prog_path,
            f"OP={int(ctx.label_type)}",
            f"EDGE_SHAPE={int(ctx.edge_shape)}",
            f"L={ctx.height_mm:g}",
            f"W={ctx.width_mm:g}",
            f"lock={lock_h:g}",
        ]
        parts.extend(f"h{i + 1}={h:g}" for i, h in enumerate(ctx.hinge_heights))

        icon = (ctx.engraving_data or {}).get('icon_filename')
        if icon:
            parts.append(f"engrave={icon}")
            for i in range(1, 6):
                val = ctx.engraving_data.get(f'p{i}')
                if val is not None:
                    parts.append(f"p{i}={val}")

        return "|".join(parts)
