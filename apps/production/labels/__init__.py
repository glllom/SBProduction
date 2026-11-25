"""
Пакет генерации производственных наклеек для BarTender и станков ЧПУ (apps.production.labels).

Содержит однопроходный генератор DoorLabelGenerator, который строит записи таблицы DoorLabel
из полностью рассчитанной спецификации (после выравнивания высот замков в партии)
без дополнительных запросов к БД.
"""

from .generator import DoorLabelGenerator

__all__ = ['DoorLabelGenerator']
