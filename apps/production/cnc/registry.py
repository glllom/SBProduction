"""
Реестр и базовый контракт драйверов станков ЧПУ (apps.production.cnc.registry).

Назначение модуля:
    Отвязывает генерацию наклеек (DoorLabelGenerator) и экспорт файлов ЧПУ от
    конкретных моделей станков. Все правила синтаксиса QR-кодов и генерации файлов
    вынесены в отдельные независимые драйверы внутри пакета apps/production/cnc/.

Как добавить новый станок ЧПУ (например, Biesse или Homag):
    1. Создайте файл apps/production/cnc/biesse.py.
    2. Унаследуйте класс от BaseMachineDriver и повесьте декоратор:
           @register_machine("BIESSE", label="Biesse Rover")
           class BiesseDriver(BaseMachineDriver):
               def build_qr_payload(self, ctx: MachineContext) -> str:
                   ...
    3. Перезапустите сервер и выберите "Biesse Rover" у нужной станции в админке.
    Никакие файлы ядра редактировать не нужно.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Iterator

if TYPE_CHECKING:
    from apps.production.library import LibraryBuildScope

from apps.production.registry_utils import autodiscover_package


@dataclass(frozen=True)
class MachineContext:
    """
    Нормализованный контекст одной наклейки/операции, передаваемый в драйвер ЧПУ.

    Единицы измерения:
        - width_mm, height_mm, thickness_mm: уже переведены в МИЛЛИМЕТРЫ.
        - lock_height, hinge_heights: высоты в сантиметрах (в формате, ожидаемом станками).
    """
    order_number: str
    item_mark: str
    label_type: int
    leaf_role: int

    width_mm: float
    height_mm: float
    thickness_mm: float

    edge_type: str = 'STANDARD'
    edge_shape: bool = False
    cnc_program: str = ''

    lock_height: Optional[float] = None
    hinge_heights: List[float] = field(default_factory=list)
    engraving_data: Dict[str, Any] = field(default_factory=dict)

    # Ссылка на полную спецификацию позиции (если новому станку потребуются доп. поля)
    spec: Any = None


class BaseMachineDriver(ABC):
    """
    Базовый интерфейс драйвера станка ЧПУ.

    Каждый станок обязан реализовать build_qr_payload() для печати наклеек BarTender
    и при необходимости может переопределить generate_files() для выгрузки файлов
    (XML, PGMX, MPR и др.) на сервер или в ZIP-архив.
    """

    code: str = ''
    label: str = ''
    # Включите True в подклассе, если драйвер реализует build_library()
    supports_library: bool = False

    @abstractmethod
    def build_qr_payload(self, ctx: MachineContext) -> str:
        """
        Формирует строку QR-кода для конкретной операции (наклейки 0, 1 или 2).

        Args:
            ctx: MachineContext с габаритами в мм, программами и высотами фурнитуры.

        Returns:
            Готовая строка для записи в DoorLabel.qr_payload.
        """
        raise NotImplementedError

    def generate_files(self, order, specs: List[Any]) -> Dict[str, bytes]:
        """
        Опциональный генератор управляющих файлов ЧПУ для заказа.

        Args:
            order: Объект заказа (apps.orders.models.Order).
            specs: Список ProductionSpec позиций, попавших в выгрузку.

        Returns:
            Словарь {относительный_путь_файла: содержимое_в_байтах},
            например {'doors/door_1/hinges.xml': b'<?xml ...>'}.
            По умолчанию пустой словарь (станок работает только по QR-кодам).
        """
        return {}

    def build_library(self, scope: LibraryBuildScope) -> Iterator[Tuple[str, bytes]]:
        """
        Опциональный потоковый генератор библиотеки макросов / исполняемых файлов станка.

        Использует yield (относительный_путь, байты), чтобы пересборка тысяч файлов
        не требовала хранения всей библиотеки в оперативной памяти.

        Пример:
            yield "DoorModel/LockA/HingeB/Front01.pgmx", rendered_text.encode('utf-8')
        """
        raise NotImplementedError(
            f"Драйвер '{self.code}' не реализует генерацию библиотеки (build_library)."
        )


class MachineRegistry:
    """
    Центральный реестр всех зарегистрированных драйверов ЧПУ.

    Автоматически подгружает модули пакета apps.production.cnc при первом обращении,
    поэтому работает одинаково надёжно в runserver, management-командах и тестах.
    """

    _drivers: Dict[str, BaseMachineDriver] = {}

    @classmethod
    def ensure_discovered(cls) -> None:
        """Гарантирует, что все файлы внутри apps/production/cnc/ импортированы."""
        autodiscover_package('apps.production.cnc')

    @classmethod
    def register(cls, code: str, label: str, driver_cls: Type[BaseMachineDriver]) -> Type[BaseMachineDriver]:
        """Регистрирует класс драйвера под уникальным строковым кодом станка."""
        normalized_code = code.strip().upper()
        if not normalized_code:
            raise ValueError("Код драйвера станка ЧПУ не может быть пустым.")

        driver_cls.code = normalized_code
        driver_cls.label = label
        cls._drivers[normalized_code] = driver_cls()
        return driver_cls

    @classmethod
    def get(cls, code: Optional[str], fallback: str = 'ACCORD_STD') -> BaseMachineDriver:
        """
        Возвращает экземпляр драйвера по коду станка.
        Если код не найден (например, станок удалили из кода, но он остался в старой записи),
        безопасно возвращает драйвер по умолчанию (ACCORD_STD).
        """
        cls.ensure_discovered()
        key = (code or '').strip().upper()
        if key in cls._drivers:
            return cls._drivers[key]
        if fallback in cls._drivers:
            return cls._drivers[fallback]
        raise KeyError(f"Драйвер ЧПУ '{code}' не зарегистрирован и fallback '{fallback}' недоступен.")

    @classmethod
    def get_or_none(cls, code: Optional[str]) -> Optional[BaseMachineDriver]:
        """Возвращает драйвер по коду или None, если такой станок не зарегистрирован."""
        cls.ensure_discovered()
        key = (code or '').strip().upper()
        return cls._drivers.get(key)

    @classmethod
    def all_drivers(cls) -> List[BaseMachineDriver]:
        """Возвращает список всех зарегистрированных драйверов (в порядке регистрации)."""
        cls.ensure_discovered()
        return list(cls._drivers.values())

    @classmethod
    def choices(cls, include_empty: bool = True, empty_label: str = 'ללא שיוך למכונה') -> List[Tuple[str, str]]:
        """
        Формирует список (code, label) для выпадающих списков в формах админки.
        Позволяет подключать новые станки без создания Django-миграций.
        """
        cls.ensure_discovered()
        items = [(drv.code, drv.label) for drv in cls._drivers.values()]
        if include_empty:
            return [('', empty_label)] + items
        return items

    @classmethod
    def library_drivers(cls) -> List[BaseMachineDriver]:
        """Возвращает только драйверы, поддерживающие генерацию библиотеки макросов."""
        cls.ensure_discovered()
        return [drv for drv in cls._drivers.values() if getattr(drv, 'supports_library', False)]

    @classmethod
    def library_choices(cls) -> List[Tuple[str, str]]:
        """Список (code, label) для выбора станка в конструкторе библиотек."""
        return [(drv.code, drv.label) for drv in cls.library_drivers()]


def register_machine(code: str, label: str):
    """
    Декоратор регистрации драйвера станка ЧПУ.

    Пример:
        @register_machine("ESSEPIGI", label="Essepigi")
        class EssepigiDriver(BaseMachineDriver):
            ...
    """

    def _decorator(driver_cls: Type[BaseMachineDriver]) -> Type[BaseMachineDriver]:
        return MachineRegistry.register(code=code, label=label, driver_cls=driver_cls)

    return _decorator
