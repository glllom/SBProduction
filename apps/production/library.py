"""
Инфраструктура генерации библиотек макросов и исполняемых файлов ЧПУ (apps.production.cnc.library).

Назначение модуля:
    - LibraryBuildScope: единый объект фильтров (семьи, модели, замки, петли, фасады,
      кастомизаторы) для полной или частичной пересборки библиотеки напрямую из БД Django.
    - render_cnc_template / render_cnc_template_file: рендер текстовых CNC-файлов
      с синтаксисом Django Templates ({{ var }}, {% for %}, {% if %}), но с отключённым
      HTML-экранированием (autoescape=False), чтобы не портить <, >, &, " в XML/PGMX/G-code.
    - safe_path_segment: очистка сегментов путей от запрещённых символов Windows/ЧПУ.
    - MachineLibraryService: потоковая запись библиотеки на диск, в ZIP-файл или
      в SpooledTemporaryFile (для HTTP-скачивания без переполнения RAM на 10 000+ файлах).
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from django.template import Context, Engine

if TYPE_CHECKING:
    from .registry import BaseMachineDriver

# Отдельный экземпляр Django Template Engine без HTML-экранирования для CNC-файлов
_CNC_TEMPLATE_ENGINE = Engine(autoescape=False)

# Запрещённые символы в именах файлов/папок на Windows-контроллерах станков ЧПУ
_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MULTISPACE_RE = re.compile(r'\s+')


def safe_path_segment(value: Any, fallback: str = 'unknown') -> str:
    """
    Очищает строку для безопасного использования в имени папки или файла ЧПУ.
    Убирает запрещённые символы Windows (<>:"/\\|?*), сжимает пробелы и крайние точки.
    """
    raw = str(value or '').strip()
    cleaned = _INVALID_PATH_CHARS_RE.sub('_', raw)
    cleaned = _MULTISPACE_RE.sub(' ', cleaned).strip(' .')
    return cleaned or fallback


def render_cnc_template(template_source: str, context: Dict[str, Any]) -> str:
    """
    Рендерит текстовый CNC-шаблон (PGMX, XML, MPR, CIX, G-code) с поддержкой
    {{ var }}, {% if %}, {% for %} и отключённым HTML-экранированием.
    """
    template = _CNC_TEMPLATE_ENGINE.from_string(template_source)
    return template.render(Context(context, autoescape=False))


def render_cnc_template_file(template_path: Union[str, Path], context: Dict[str, Any]) -> str:
    """Читает шаблон CNC с диска (например, из папки плагина) и рендерит его."""
    source = Path(template_path).read_text(encoding='utf-8')
    return render_cnc_template(source, context)


@dataclass(frozen=True)
class LibraryBuildScope:
    """
    Область пересборки библиотеки макросов станка.

    Если список ID равен None или пуст — берутся все активные записи из БД.
    Если заданы конкретные ID (например, lock_ids=[12]) — драйвер пересобирает
    только соответствующую ветку дерева библиотеки.
    """
    family_ids: Optional[Tuple[int, ...]] = None
    model_ids: Optional[Tuple[int, ...]] = None
    lock_ids: Optional[Tuple[int, ...]] = None
    hinge_ids: Optional[Tuple[int, ...]] = None
    front_ids: Optional[Tuple[int, ...]] = None
    customizer_ids: Optional[Tuple[int, ...]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_partial(self) -> bool:
        """Возвращает True, если задан хотя бы один фильтр частичной пересборки."""
        return any((
            self.family_ids,
            self.model_ids,
            self.lock_ids,
            self.hinge_ids,
            self.front_ids,
            self.customizer_ids,
        ))

    def get_families(self):
        """Активные семейства продуктов с учётом фильтра family_ids."""
        from apps.catalog.models import ProductFamily

        qs = ProductFamily.objects.filter(active=True).select_related('product_type').order_by('id')
        if self.family_ids:
            qs = qs.filter(id__in=self.family_ids)
        return qs

    def get_models(self):
        """Активные модели продуктов с учётом фильтров model_ids и family_ids."""
        from apps.catalog.models import ProductModel

        qs = ProductModel.objects.filter(active=True).select_related('product_family', 'series').order_by('id')
        if self.family_ids:
            qs = qs.filter(product_family_id__in=self.family_ids)
        if self.model_ids:
            qs = qs.filter(id__in=self.model_ids)
        return qs

    def get_locks(self):
        """Активные замки с учётом фильтра lock_ids."""
        from apps.catalog.models import Hardware

        qs = Hardware.objects.filter(active=True, role=Hardware.HardwareRole.LOCK).order_by('id')
        if self.lock_ids:
            qs = qs.filter(id__in=self.lock_ids)
        return qs

    def get_hinges(self):
        """Активные петли с учётом фильтра hinge_ids."""
        from apps.catalog.models import Hardware

        qs = Hardware.objects.filter(active=True, role=Hardware.HardwareRole.HINGE).order_by('id')
        if self.hinge_ids:
            qs = qs.filter(id__in=self.hinge_ids)
        return qs

    def get_fronts(self):
        """Активные фасады/отделки с учётом фильтра front_ids."""
        from apps.catalog.models import Front

        qs = Front.objects.filter(active=True).select_related('series').order_by('id')
        if self.front_ids:
            qs = qs.filter(id__in=self.front_ids)
        return qs

    def get_customizers(self):
        """Активные кастомизаторы с учётом фильтра customizer_ids."""
        from apps.catalog.models import Customizer

        qs = Customizer.objects.filter(active=True).order_by('id')
        if self.customizer_ids:
            qs = qs.filter(id__in=self.customizer_ids)
        return qs

    def get_hardware_macros(self, role: Optional[str] = None):
        """Записи HardwareMacroFile с предзагрузкой фурнитуры и семейств."""
        from apps.engineering.models import HardwareMacroFile

        qs = (
            HardwareMacroFile.objects.select_related('machining_feature')
            .prefetch_related('hardware', 'door_families')
            .order_by('id')
        )
        if role:
            qs = qs.filter(hardware__role=role)
        if self.family_ids:
            qs = qs.filter(door_families__id__in=self.family_ids)

        hw_ids: List[int] = []
        if self.lock_ids:
            hw_ids.extend(self.lock_ids)
        if self.hinge_ids:
            hw_ids.extend(self.hinge_ids)
        if hw_ids:
            qs = qs.filter(hardware__id__in=hw_ids)
        return qs.distinct()

    def get_perimeter_files(self):
        """Записи PerimeterRoutingFile с учётом фильтра family_ids."""
        from apps.engineering.models import PerimeterRoutingFile

        qs = PerimeterRoutingFile.objects.prefetch_related('doors').order_by('id')
        if self.family_ids:
            qs = qs.filter(doors__id__in=self.family_ids).distinct()
        return qs

    def get_front_engravings(self):
        """Записи FrontEngravingFile с учётом фильтра front_ids."""
        from apps.engineering.models import FrontEngravingFile

        qs = FrontEngravingFile.objects.select_related('front', 'front__series').order_by('id')
        if self.front_ids:
            qs = qs.filter(front_id__in=self.front_ids)
        return qs

    def get_customizer_macros(self):
        """Записи CustomizerMacroFile с учётом фильтра customizer_ids."""
        from apps.engineering.models import CustomizerMacroFile

        qs = CustomizerMacroFile.objects.select_related('customizer').order_by('id')
        if self.customizer_ids:
            qs = qs.filter(customizer_id__in=self.customizer_ids)
        return qs


@dataclass
class LibraryBuildResult:
    """Сводная статистика по результатам сборки или предпросмотра библиотеки."""
    machine_code: str
    machine_label: str
    files_count: int = 0
    total_bytes: int = 0
    sample_paths: List[str] = field(default_factory=list)
    output_path: Optional[str] = None

    @property
    def total_kb(self) -> float:
        return round(self.total_bytes / 1024.0, 2)

    @property
    def total_mb(self) -> float:
        return round(self.total_bytes / (1024.0 * 1024.0), 2)


class MachineLibraryService:
    """
    Универсальный потоковый сборщик библиотек для любого драйвера ЧПУ,
    у которого supports_library = True.
    """

    # Порог сброса временного ZIP из оперативной памяти на диск (10 МБ)
    SPOOL_MAX_MEMORY_BYTES = 10 * 1024 * 1024

    @staticmethod
    def _ensure_supported(driver: BaseMachineDriver) -> None:
        if not getattr(driver, 'supports_library', False):
            raise ValueError(
                f"Драйвер станка '{driver.code}' ({driver.label}) не поддерживает "
                f"автогенерацию библиотеки (supports_library = False)."
            )

    @staticmethod
    def _normalize_rel_path(rel_path: str) -> str:
        """Нормализует относительный путь файла и блокирует выход за пределы корня (..)."""
        cleaned = str(rel_path or '').replace('\\', '/').lstrip('/')
        parts = [p for p in cleaned.split('/') if p and p != '.']
        if not parts or any(p == '..' for p in parts):
            raise ValueError(f"Некорректный относительный путь файла библиотеки: '{rel_path}'")
        return '/'.join(parts)

    @classmethod
    def preview(
            cls,
            driver: BaseMachineDriver,
            scope: Optional[LibraryBuildScope] = None,
            max_samples: int = 30,
    ) -> LibraryBuildResult:
        """
        Выполняет dry-run генерации без записи на диск: подсчитывает количество файлов,
        итоговый объём и собирает первые max_samples путей для проверки структуры дерева.
        """
        cls._ensure_supported(driver)
        active_scope = scope or LibraryBuildScope()
        result = LibraryBuildResult(machine_code=driver.code, machine_label=driver.label)

        for rel_path, content in driver.build_library(active_scope):
            norm_path = cls._normalize_rel_path(rel_path)
            result.files_count += 1
            result.total_bytes += len(content)
            if len(result.sample_paths) < max_samples:
                result.sample_paths.append(norm_path)

        return result

    @classmethod
    def build_to_directory(
            cls,
            driver: BaseMachineDriver,
            output_dir: Union[str, Path],
            scope: Optional[LibraryBuildScope] = None,
            clean: bool = False,
            max_samples: int = 30,
    ) -> LibraryBuildResult:
        """Потоково записывает сгенерированную библиотеку в указанную папку на диске."""
        cls._ensure_supported(driver)
        active_scope = scope or LibraryBuildScope()

        root = Path(output_dir).resolve()
        if clean and root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)

        result = LibraryBuildResult(
            machine_code=driver.code,
            machine_label=driver.label,
            output_path=str(root),
        )

        for rel_path, content in driver.build_library(active_scope):
            norm_path = cls._normalize_rel_path(rel_path)
            target = (root / norm_path).resolve()
            if root not in target.parents:
                raise ValueError(f"Путь '{rel_path}' выходит за пределы каталога назначения.")

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

            result.files_count += 1
            result.total_bytes += len(content)
            if len(result.sample_paths) < max_samples:
                result.sample_paths.append(norm_path)

        return result

    @classmethod
    def _write_to_zip(
            cls,
            driver: BaseMachineDriver,
            zf: zipfile.ZipFile,
            scope: LibraryBuildScope,
            max_samples: int = 30,
    ) -> LibraryBuildResult:
        """Общий потоковый цикл упаковки файлов драйвера в открытый ZipFile."""
        result = LibraryBuildResult(machine_code=driver.code, machine_label=driver.label)
        for rel_path, content in driver.build_library(scope):
            norm_path = cls._normalize_rel_path(rel_path)
            zf.writestr(norm_path, content)
            result.files_count += 1
            result.total_bytes += len(content)
            if len(result.sample_paths) < max_samples:
                result.sample_paths.append(norm_path)
        return result

    @classmethod
    def build_to_zip_file(
            cls,
            driver: BaseMachineDriver,
            zip_path: Union[str, Path],
            scope: Optional[LibraryBuildScope] = None,
            max_samples: int = 30,
    ) -> LibraryBuildResult:
        """Потоково упаковывает библиотеку в ZIP-архив на диске (для CLI / скриптов)."""
        cls._ensure_supported(driver)
        active_scope = scope or LibraryBuildScope()

        target = Path(zip_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(target, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            result = cls._write_to_zip(driver, zf, active_scope, max_samples=max_samples)

        result.output_path = str(target)
        return result

    @classmethod
    def build_to_spooled_zip(
            cls,
            driver: BaseMachineDriver,
            scope: Optional[LibraryBuildScope] = None,
            max_samples: int = 30,
    ) -> Tuple[tempfile.SpooledTemporaryFile, LibraryBuildResult]:
        """
        Потоково собирает ZIP-архив во временный SpooledTemporaryFile (для Django FileResponse).
        До 10 МБ хранится в RAM, при большем объёме автоматически сбрасывается на диск.
        """
        cls._ensure_supported(driver)
        active_scope = scope or LibraryBuildScope()

        spooled = tempfile.SpooledTemporaryFile(max_size=cls.SPOOL_MAX_MEMORY_BYTES)
        try:
            with zipfile.ZipFile(spooled, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
                result = cls._write_to_zip(driver, zf, active_scope, max_samples=max_samples)
            spooled.seek(0)
            return spooled, result
        except Exception:
            spooled.close()
            raise
