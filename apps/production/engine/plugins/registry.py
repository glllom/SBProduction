"""
Реестр и базовый контракт плагинов нестандартных кастомизаторов (apps.production.engine.plugins.registry).

Назначение модуля:
    Отделяет специфическую инженерную математику отдельных кастомизаторов
    (двустворчатые двери, деревянный кант, нестандартные наличники, скрытые доводчики и т.д.)
    от базового расчётного ядра OrderSpecEngine.

Точки подключения (хуки) в жизненном цикле расчёта одной двери:
    1. on_init        — сразу после init_item_state (разбор параметров par1..par5, установка флагов).
    2. on_geometry    — сразу после calculate_geometry (корректировка panel/press_dimensions, cut_sheets).
    3. on_before_bom  — перед calculate_bom (подмена слотов в state.effective_bom).
    4. on_bom         — сразу после calculate_bom (добавление/изменение позиций в spec.bom_items).
    5. on_hardware    — сразу после calculate_hardware (нестандартные высоты/слоты фурнитуры).
    6. on_routing     — сразу после calculate_routing (изменение маршрута станций и cnc_targets).
    7. on_visuals     — сразу после calculate_visuals (добавление/изменение SVG-блоков пресса).

Как добавить новый нестандартный кастомизатор завтра:
    1. Создайте файл apps/production/engine/plugins/<my_plugin>.py:
           @register_customizer("MY_FEATURE", label="תיאור בעברית")
           class MyFeaturePlugin(BaseCustomizerPlugin):
               def on_geometry(self, state, gc, cache):
                   ...
    2. Перезапустите сервер и выберите "תיאור בעברית" в поле plugin_code кастомизатора в админке.
    Никакие файлы ядра менять не нужно.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Type

from apps.production.registry_utils import autodiscover_package

if TYPE_CHECKING:
    from apps.orders.models import OrderItemsGroupCustomizer
    from apps.production.engine.cache import OrderReferenceCache
    from apps.production.engine.calculators.base import ItemRuntimeState


class BaseCustomizerPlugin:
    """
    Базовый класс плагина кастомизатора.

    Наследник переопределяет только те хуки, которые ему действительно нужны;
    остальные методы по умолчанию ничего не делают.
    Атрибут priority задаёт порядок выполнения между плагинами на одном этапе
    (меньшее число выполняется раньше).
    """

    code: str = ''
    label: str = ''
    priority: int = 100

    def on_init(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после базовой инициализации позиции (init_item_state)."""

    def on_geometry(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после базового расчёта геометрии (calculate_geometry)."""

    def on_before_bom(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается перед сборкой BOM (для патча слотов state.effective_bom)."""

    def on_bom(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после сборки BOM (для добавления или правки spec.bom_items)."""

    def on_hardware(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после расчёта фурнитуры и её высот (calculate_hardware)."""

    def on_routing(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после расчёта маршрута станций и станков ЧПУ (calculate_routing)."""

    def on_visuals(
            self,
            state: ItemRuntimeState,
            gc: OrderItemsGroupCustomizer,
            cache: OrderReferenceCache,
    ) -> None:
        """Вызывается после построения SVG-пазла для пресса (calculate_visuals)."""


class CustomizerPluginRegistry:
    """
    Центральный реестр плагинов кастомизаторов.

    Разрешение плагина для записи Customizer:
        1. Явное поле customizer.plugin_code (основной способ).
        2. Fallback по токенам поля customizer.tag (для обратной совместимости).
    """

    _plugins: Dict[str, BaseCustomizerPlugin] = {}
    _aliases: Dict[str, str] = {}

    @classmethod
    def ensure_discovered(cls) -> None:
        """Гарантирует импорт всех модулей в apps/production/engine/plugins/."""
        autodiscover_package('apps.production.engine.plugins')

    @classmethod
    def register(
            cls,
            code: str,
            label: str,
            plugin_cls: Type[BaseCustomizerPlugin],
            aliases: Tuple[str, ...] = (),
    ) -> Type[BaseCustomizerPlugin]:
        """Регистрирует класс плагина под уникальным кодом и опциональными псевдонимами."""
        key = code.strip().upper()
        if not key:
            raise ValueError("Код плагина кастомизатора не может быть пустым.")

        plugin_cls.code = key
        plugin_cls.label = label
        cls._plugins[key] = plugin_cls()

        for alias in aliases:
            alias_key = alias.strip().upper()
            if alias_key:
                cls._aliases[alias_key] = key

        return plugin_cls

    @classmethod
    def get_or_none(cls, code: Optional[str]) -> Optional[BaseCustomizerPlugin]:
        """Возвращает экземпляр плагина по коду/псевдониму или None."""
        cls.ensure_discovered()
        key = (code or '').strip().upper()
        if not key:
            return None
        if key in cls._plugins:
            return cls._plugins[key]
        if key in cls._aliases:
            return cls._plugins[cls._aliases[key]]
        return None

    @classmethod
    def resolve_for_customizer(cls, customizer) -> Optional[BaseCustomizerPlugin]:
        """
        Определяет плагин для модели catalog.Customizer:
            1. По явному полю plugin_code.
            2. Fallback по тегам (customizer.tag).
        """
        cls.ensure_discovered()

        plugin_code = (getattr(customizer, 'plugin_code', '') or '').strip().upper()
        if plugin_code:
            return cls.get_or_none(plugin_code)

        raw_tag = (getattr(customizer, 'tag', '') or '').upper()
        for token in raw_tag.replace(',', ' ').split():
            plugin = cls.get_or_none(token)
            if plugin is not None:
                return plugin
        return None

    @classmethod
    def resolve_for_item(
            cls,
            customizers: List[OrderItemsGroupCustomizer],
    ) -> List[Tuple[BaseCustomizerPlugin, OrderItemsGroupCustomizer]]:
        """
        Возвращает упорядоченный по priority список пар (plugin, group_customizer)
        для всех кастомизаторов группы, у которых есть зарегистрированный плагин.
        """
        cls.ensure_discovered()
        resolved: List[Tuple[BaseCustomizerPlugin, OrderItemsGroupCustomizer]] = []
        seen_keys = set()

        for gc in customizers:
            plugin = cls.resolve_for_customizer(gc.customizer)
            if plugin is None:
                continue
            dedup_key = (plugin.code, gc.id)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            resolved.append((plugin, gc))

        resolved.sort(key=lambda pair: (pair[0].priority, pair[0].code))
        return resolved

    @classmethod
    def choices(
            cls,
            include_empty: bool = True,
            empty_label: str = 'ללא פלאגין (הגדרות רגילות מהמערכת)',
    ) -> List[Tuple[str, str]]:
        """Формирует список (code, label) для динамического выпадающего списка в админке."""
        cls.ensure_discovered()
        items = sorted(
            ((p.code, p.label) for p in cls._plugins.values()),
            key=lambda pair: pair[0],
        )
        if include_empty:
            return [('', empty_label)] + items
        return items


def register_customizer(code: str, label: str, aliases: Tuple[str, ...] = ()):
    """
    Декоратор регистрации плагина кастомизатора.

    Пример:
        @register_customizer("WOOD_EDGE", label="קנט עץ (חישוב פרס ומדבקה 0)")
        class WoodEdgePlugin(BaseCustomizerPlugin):
            ...
    """

    def _decorator(plugin_cls: Type[BaseCustomizerPlugin]) -> Type[BaseCustomizerPlugin]:
        return CustomizerPluginRegistry.register(
            code=code,
            label=label,
            plugin_cls=plugin_cls,
            aliases=aliases,
        )

    return _decorator
