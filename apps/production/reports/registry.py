"""
Реестр и базовый контракт печатных отчётов производственных станций (apps.production.reports.registry).

Назначение модуля:
    Полностью устраняет хардкод if/elif по station.code и template_name в views.py.
    Каждый тип производственного отчёта оформляется как изолированный класс-наследник
    BaseStationReport и регистрируется декоратором @register_report(code, label).

Как добавить новый нестандартный отчёт (например, "Стеклопакеты / זיגוג"):
    1. Создайте файл apps/production/reports/glazing.py:
           @register_report("glazing", label='דו"ח זיגוג')
           class GlazingStationReport(BaseStationReport):
               template_name = "production/reports/report_glazing.html"
               include_template = "production/includes/report_glazing.html"

               def get_extra_context(self, ctx: ReportContext) -> dict:
                   return {"glass_rows": ...}
    2. Перезапустите сервер и выберите 'דו"ח זיגוג' в поле report_handler нужной станции в админке.
    3. Если станции нужен обычный табличный отчёт — код писать вообще не нужно:
       оставьте report_handler пустым (или 'generic') и укажите путь к HTML-шаблону.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

from django.utils import timezone

from apps.engineering.models import ProductionStation
from apps.production.registry_utils import autodiscover_package


@dataclass
class ReportContext:
    """
    Унифицированный набор входных данных для построения любого отчёта станции
    (как в автономном режиме, так и в виде секции внутри Master Print).
    """
    order: Any
    order_spec: Any
    station: Optional[ProductionStation]
    station_code: str
    station_items: List[Any]
    filtered_db_items: List[Any] = field(default_factory=list)
    batches_label: str = ""
    stage_label: str = ""
    station_comment: str = ""
    order_qr: str = ""
    barcode_text: str = ""
    requested_batches: List[str] = field(default_factory=list)
    is_master: bool = False


class BaseStationReport:
    """
    Базовый класс обработчика отчёта производственной станции.

    Подклассы переопределяют только нужные атрибуты (template_name, include_template,
    is_portrait, default_label) и метод get_extra_context(ctx) для расчёта
    специфических данных отчёта.
    """

    code: str = 'generic'
    label: str = 'דו"ח טבלאי סטנדרטי (Generic)'

    # Путь к автономному HTML-шаблону (если None — берётся station.template_name)
    template_name: Optional[str] = None
    # Путь к подключаемой секции для Master Print (если None — выводится из template_name)
    include_template: Optional[str] = None
    # Книжная ориентация страницы в Master Print (True для пресса и деревянных коробок)
    is_portrait: bool = False
    # Заголовок по умолчанию, если у станции не заданы label и name
    default_label: str = 'דו"ח ייצור'
    # Требуется ли расчёт спецификации (OrderSpec) для автономного рендера (False для склада)
    requires_spec: bool = True

    def resolve_template_name(self, ctx: ReportContext) -> str:
        """Определяет HTML-шаблон для автономного открытия отчёта станции."""
        if ctx.station and ctx.station.template_name:
            return ctx.station.template_name
        if self.template_name:
            return self.template_name
        return 'production/reports/alum_frames_report.html'

    def resolve_include_template(self, ctx: ReportContext) -> str:
        """Определяет HTML-фрагмент для вставки секции в Master Print."""
        if self.include_template:
            return self.include_template

        if ctx.station and ctx.station.template_name:
            base_name = (
                ctx.station.template_name.split('/')[-1]
                .replace('_report.html', '')
                .replace('.html', '')
            )
            if not base_name.startswith('report_'):
                base_name = f'report_{base_name}'
            return f'production/includes/{base_name}.html'

        return 'production/includes/report_alum_frames.html'

    def resolve_report_label(self, ctx: ReportContext) -> str:
        """Возвращает отображаемое название отчёта для шапки печатного листа."""
        if ctx.station:
            return ctx.station.label or ctx.station.name or self.default_label
        return self.default_label

    def get_extra_context(self, ctx: ReportContext) -> Dict[str, Any]:
        """
        Точка расширения для подклассов: возвращает специфические переменные
        шаблона (например, panel_groups, frame_groups, facings_data).
        """
        return {}

    def build_context(self, ctx: ReportContext) -> Dict[str, Any]:
        """Собирает полный контекст рендера для автономной страницы отчёта."""
        spec_json = (
            ctx.order_spec.model_dump(by_alias=True)
            if ctx.order_spec is not None and hasattr(ctx.order_spec, 'model_dump')
            else ctx.order_spec
        )
        base_context: Dict[str, Any] = {
            'order': ctx.order,
            'has_special_detail': self._has_special_detail(ctx),
            'order_spec': ctx.order_spec,
            'spec_json': spec_json,
            'station': ctx.station,
            'station_comment': ctx.station_comment,
            'report_label': self.resolve_report_label(ctx),
            'batches_label': ctx.batches_label,
            'stage_label': ctx.stage_label,
            'spec_items': ctx.station_items,
            'order_qr': ctx.order_qr,
            'barcode_text': ctx.barcode_text,
            'now': timezone.now(),

        }
        base_context.update(self.get_extra_context(ctx))
        return base_context

    def build_master_section(self, ctx: ReportContext) -> Dict[str, Any]:
        """Собирает словарь секции для сводного документа Master Print."""
        extra = self.get_extra_context(ctx)
        section: Dict[str, Any] = {
            'has_special_detail': self._has_special_detail(ctx),
            'station': ctx.station,
            'station_code': ctx.station.code if ctx.station else ctx.station_code,
            'station_comment': ctx.station_comment,
            'report_label': self.resolve_report_label(ctx),
            'batches_label': ctx.batches_label,
            'order_spec': ctx.order_spec,
            'spec_items': ctx.station_items,
            'include_template': self.resolve_include_template(ctx),
            'order_qr': ctx.order_qr,
            'is_portrait': self.is_portrait,
            # Безопасные значения по умолчанию для шаблонов includes/*.html
            'groups_data': [],
            'enriched_frames_items': [],
            'enriched_doors_items': [],
            'panel_groups': [],
            'frame_groups': [],
            'hardware_summary': [],
        }
        section.update(extra)
        return section

    def _has_special_detail(self, ctx: ReportContext) -> bool:
        """Возвращает True, если среди позиций этого отчёта есть группа с флагом פרט מיוחד."""
        from apps.orders.models import OrderItemsGroup

        if ctx.station_items:
            active_ids = {
                getattr(it, 'item_id', None) if hasattr(it, 'item_id') else it.get('item_id')
                for it in ctx.station_items
            }
            group_ids = {
                it.group_id for it in ctx.filtered_db_items
                if it.id in active_ids and getattr(it, 'group_id', None)
            }
            if not group_ids:
                return False
            return OrderItemsGroup.objects.filter(id__in=group_ids, is_special_detail=True).exists()

        if ctx.filtered_db_items:
            group_ids = {it.group_id for it in ctx.filtered_db_items if getattr(it, 'group_id', None)}
            qs = OrderItemsGroup.objects.filter(id__in=group_ids, is_special_detail=True)
        elif not self.requires_spec and ctx.order:
            qs = ctx.order.groups.filter(is_special_detail=True).exclude(
                production_state=OrderItemsGroup.ProductionState.CANCELED
            )
        else:
            return False

        if ctx.requested_batches:
            batch_nums = [int(b) for b in ctx.requested_batches if str(b).isdigit()]
            if batch_nums:
                qs = qs.filter(batch_number__in=batch_nums)

        return qs.exists()


class ReportRegistry:
    """
    Центральный реестр обработчиков отчётов производственных станций.

    Поддерживает:
        - явный выбор обработчика по полю ProductionStation.report_handler;
        - автоматический подбор по legacy-коду/шаблону (если report_handler пуст);
        - генерацию choices() для динамического выпадающего списка в админке.
    """

    _handlers: Dict[str, BaseStationReport] = {}
    _aliases: Dict[str, str] = {}

    @classmethod
    def ensure_discovered(cls) -> None:
        """Гарантирует импорт всех модулей отчётов в apps/production/reports/."""
        autodiscover_package('apps.production.reports')

    @classmethod
    def register(
            cls,
            code: str,
            label: str,
            handler_cls: Type[BaseStationReport],
            aliases: Tuple[str, ...] = (),
    ) -> Type[BaseStationReport]:
        """Регистрирует класс отчёта под уникальным кодом и необязательными псевдонимами."""
        key = code.strip().lower()
        if not key:
            raise ValueError("Код обработчика отчёта не может быть пустым.")

        handler_cls.code = key
        handler_cls.label = label
        cls._handlers[key] = handler_cls()

        for alias in aliases:
            alias_key = alias.strip().lower()
            if alias_key:
                cls._aliases[alias_key] = key

        return handler_cls

    @classmethod
    def get(cls, code: Optional[str]) -> BaseStationReport:
        """Возвращает обработчик по коду или псевдониму (fallback — 'generic')."""
        cls.ensure_discovered()
        key = (code or '').strip().lower()
        if key in cls._handlers:
            return cls._handlers[key]
        if key in cls._aliases:
            return cls._handlers[cls._aliases[key]]
        return cls._handlers['generic']

    @classmethod
    def resolve_for_station(
            cls,
            station: Optional[ProductionStation] = None,
            station_code: Optional[str] = None,
    ) -> BaseStationReport:
        """
        Определяет обработчик отчёта для станции:
            1. Явное поле station.report_handler (приоритет №1).
            2. Прямое совпадение station.code / station_code по кодам и псевдонимам.
            3. Подсказка по station.template_name (для legacy-станций без report_handler).
            4. Универсальный GenericStationReport.
        """
        cls.ensure_discovered()

        # 1. Явная привязка в БД (целевой способ)
        if station and getattr(station, 'report_handler', ''):
            return cls.get(station.report_handler)

        # 2. Спецслучай: код 'frames' может быть деревянным или алюминиевым по шаблону
        code_low = ((station.code if station else None) or station_code or '').strip().lower()
        tmpl_low = (getattr(station, 'template_name', '') or '').lower()

        if code_low == 'frames' and 'wood' in tmpl_low:
            return cls.get('wood_frames')

        # 3. Поиск по коду или псевдонимам
        if code_low in cls._handlers:
            return cls._handlers[code_low]
        if code_low in cls._aliases:
            return cls._handlers[cls._aliases[code_low]]

        # 4. Поиск по имени шаблона
        for handler_key, handler in cls._handlers.items():
            if handler_key != 'generic' and handler_key in tmpl_low:
                return handler

        return cls._handlers['generic']

    @classmethod
    def choices(
            cls,
            include_empty: bool = True,
            empty_label: str = 'אוטומטי / גנרי (לפי תבנית HTML)',
    ) -> List[Tuple[str, str]]:
        """Формирует список (code, label) для выпадающего списка в админке ProductionStation."""
        cls.ensure_discovered()
        items = [(h.code, h.label) for h in cls._handlers.values()]
        if include_empty:
            return [('', empty_label)] + items
        return items


def register_report(code: str, label: str, aliases: Tuple[str, ...] = ()):
    """
    Декоратор регистрации обработчика отчёта производственной станции.

    Пример:
        @register_report("press", label='דו"ח פרס', aliases=("cutting_press",))
        class PressStationReport(BaseStationReport):
            ...
    """

    def _decorator(handler_cls: Type[BaseStationReport]) -> Type[BaseStationReport]:
        return ReportRegistry.register(code=code, label=label, handler_cls=handler_cls, aliases=aliases)

    return _decorator
