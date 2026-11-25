# SBProduction — Архитектура и справочник проекта

**Домен:** ERP / MES-система для производства дверей (Израиль, RTL-интерфейс на иврите).

**Стек:** Django 6.x, Django REST Framework, django-unfold (админка), Pydantic v2, Bootstrap 5 + Vanilla JS, BarTender (печать наклеек из БД), ЧПУ-станки Essepigi / SCM Accord (WoodWOP / `.pgmx`) / Mecal.

**Связанная документация:**
* `DATABASE.md` — ER-диаграммы, таблицы БД и инварианты хранения данных.
* `CNC_GENERATORS.md` — полное руководство по разработке драйверов станков ЧПУ, генераторов файлов заказа и сборщиков библиотек макросов.

---

## 1. Архитектурные инварианты

1. **Строгое направление зависимостей (без циклических импортов):**

   ```text
   accounts
   catalog  <--  engineering  <--  orders  <--  production
   ```

   * `catalog` — чистые коммерческие справочники и `Customizer` (с полем `plugin_code`).
   * `engineering` — инженерные правила `ProductEngineeringRule`, `BOM`, стандарты высот, `ProductionStation` (с полями `report_handler` и `target_machine`), `ProductionRoute`, ЧПУ-макросы, SVG-пазлы.
   * `orders` — заказы, группы (вкл. `is_special_detail`), позиции, шаблоны групп, накладная склада, сервис нумерации `apps/orders/services.py`. Импортировать `apps.production.services` из `apps.orders` **запрещено**.
   * `production` — расчётное ядро (`engine/`), плагины (`engine/plugins/`), наклейки (`labels/`), ЧПУ-драйверы и генератор библиотек (`cnc/`), отчёты (`reports/`), склад, трекинг станций.

2. **Единая система единиц измерения:**

   * Всё внутри БД, `ProductEngineeringRule` и `ProductionSpec` хранится **строго в положительных сантиметрах (см)**: габариты проёма (`width`, `height`, `width_bottom`, `wall`), зазоры (`leaf_top_clearance`, `leaf_bottom_clearance`, `leaf_side_clearance`), вычеты коробки (`frame_inner_*_reduction`), толщина полотна и деревянного канта (`2.0 / 1.7 / 1.0 см`), припуск на пресс (`press_allowance`), лимиты станка Essepigi, высоты замка и петель.
   * Отрицательное значение допускается только для `lock_height` (привязка от **низа** двери вместо верха) и `double_leaf_overlap`.
   * **Единственная точка перевода `см × 10 → мм`** — `DoorLabelGenerator._cm_to_mm()` в `apps/production/labels/generator.py` при сборке данных для BarTender и ЧПУ.
   * Высота на коробке (`lock_height_on_frame`, `hinge_heights_on_frame`) = высота на полотне **`+ leaf_top_clearance`** (если замок от верха).

3. **Единые источники правды:**

   * **Геометрия и допуски модели:** `engineering.ProductEngineeringRule` (JSON, валидация через `EngineeringRulesConfig`). Иерархия слияния: `ProductFamily` → `parent_model` → `ProductModel`.
   * **Обязательные кастомизаторы:** `catalog.ProductModel.required_customizers` (с наследованием от `parent_model`). Поля `Customizer.is_required` и `BOM.required_customizers` удалены.
   * **Снимки спецификаций:** только `production.OrderSpecificationSnapshot` через `TechnicalSpecService` (`apps/production/engine/spec_gateway.py`).
   * **Цвета полотна:** везде пара полей `color_panel_outside`, `color_panel_inside` и флаг `is_door_inside_different_color` (включая `Order`, `OrderItemsGroup` и `GroupSpecification`).

4. **Ключевые производственные правила:**

   * **Раздельный монтаж (`is_split_installation`):** заказ проходит `PHASE1_PRODUCTION` (коробки) → `PHASE1_READY` (замер на объекте, ввод внутренних проёмов и высот от верха коробки) → `PHASE2_PRODUCTION` (полотна).
   * **Батчи (волны запуска):** группы запускаются волнами (`batch_number = 1, 2, ...`, дата фиксации `batch_date`). Редактирование группы менеджером разрешено в статусах `NEW`/`WAITING` или в день запуска (`batch_date == today`).
   * **Трапеция (`OrderItem.width_bottom`):** пресс, раскрой листов, подбор листов в BOM и проверка лимитов Essepigi всегда считают по `max(width, width_bottom)`.
   * **Типы наклеек `DoorLabel.LabelType`:**
     * `0` (`PRE_ROUGHING`) — первичная обрезка периметра (создаётся только при скрытом деревянном канте).
     * `1` (`ROUGHING`) — финишная обработка периметра.
     * `2` (`FINISHING`) — фрезеровка под фурнитуру, замки, гравировка.
   * **Флаг `פרט מיוחד` (`OrderItemsGroup.is_special_detail`):** переводит в `ACCORD_CUSTOM` (QR вида `C:\Ww8\PROJECTS\{order_num}\d{mark}.pgmx`) **только наклейку `2` (`FINISHING`)**. Наклейки `0` и `1` идут по стандартному маршруту.

---

## 2. Потоки данных (Runtime и Build-time)

### A. Производственный поток заказа (Runtime)

```text
Order + OrderItemsGroup + OrderItem
          │
          ▼
TechnicalSpecService.get_or_build_spec(order, phase, batch_number)
  └─ проверяет OrderSpecificationSnapshot (если нет / force_rebuild -> запускает движок)
          │
          ▼
OrderSpecEngine.execute(order, items, phase, save_labels)
  ├─ 0. OrderReferenceCache.load_for_order(...)      [1 загрузка всех справочников, 0 N+1]
  ├─ 1. calculators/base.py       + plugin.on_init
  ├─ 2. calculators/geometry.py   + plugin.on_geometry
  ├─ 3. plugin.on_before_bom      + calculators/bom.py        + plugin.on_bom
  ├─ 4. calculators/hardware.py   + plugin.on_hardware
  ├─ 5. calculators/routing.py    + plugin.on_routing
  ├─ 6. calculators/visuals.py    + plugin.on_visuals
  ├─ 7. align_batch_lock_heights                     [выравнивание замков внутри батча]
  └─ 8. DoorLabelGenerator -> MachineRegistry        [однопроходная сборка и bulk-запись DoorLabel]
          │
          ▼
OrderSpecificationSnapshot (JSON)  ──► ReportRegistry (HTML-отчёты станций и Master Print)
                                   ──► StationTrackingService (очереди станков)
                                   ──► WarehousePackingSlipService (накладная склада)
DoorLabel (SQL таблица)            ──► BarTender (печать наклеек + write-back print_count)
MachineRegistry.generate_files()   ──► Управляющие файлы заказа (напр., Mecal XML)
```

### B. Поток генерации библиотек ЧПУ (Build-time)

```text
Справочники БД (catalog + engineering) + LibraryBuildScope (полный или частичный фильтр)
          │
          ▼
CLI (manage.py build_cnc_library)  ИЛИ  Web UI (/production/cnc-library/, только is_staff)
          │
          ▼
MachineLibraryService  ──► driver.build_library(scope)  [потоковый yield (rel_path, bytes)]
          │
          ├─► Dry-Run (подсчёт файлов, объём и примеры путей)
          ├─► Дерево папок на диске / сетевом диске станка
          └─► Потоковый ZIP-архив (SpooledTemporaryFile -> FileResponse)
```

---

## 3. Модульная архитектура (3 автообнаруживаемых реестра)

При старте Django (`apps/production/apps.py → ready()`) функция `autodiscover_package()` из `apps/production/registry_utils.py` автоматически сканирует 3 пакета и регистрирует все модули (как одиночные `.py` файлы, так и подпакеты с `__init__.py`). Выпадающие списки в админке подтягиваются из реестров динамически — **добавление нового модуля не требует миграций БД и правок ядра**.

### Рецепт 1: Добавить новый станок ЧПУ (и генератор его библиотеки)
1. Создайте файл `apps/production/cnc/<machine_name>.py` (или папку-пакет `apps/production/cnc/<machine_name>/` со своими шаблонами).
2. Унаследуйте `BaseMachineDriver` и повесьте декоратор `@register_machine`:
   * `build_qr_payload(ctx)` — обязательная «Инструкция» (QR-код для наклейки);
   * `generate_files(order, specs)` — опциональные файлы под конкретный заказ;
   * `supports_library = True` + `build_library(scope)` — опциональный потоковый генератор библиотеки макросов из БД.
3. Перезапустите сервер и выберите станок в поле **מכונת CNC משויכת (`target_machine`)** нужной `ProductionStation` в админке. Если включён `supports_library = True`, станок автоматически появится в `build_cnc_library` и на странице `/production/cnc-library/`.

*(Подробные примеры, API и оба паттерна сборки библиотек см. в `CNC_GENERATORS.md`.)*

### Рецепт 2: Добавить новую станцию и печатный отчёт
* **Если нужен обычный табличный отчёт (0 строк Python):**
  1. Положите HTML-шаблон в `templates/production/reports/` (и фрагмент для Master Print в `templates/production/includes/`).
  2. Создайте `ProductionStation` в админке, выберите `specification_type = דו"ח תחנה רגיל`, оставьте `report_handler` пустым (или `generic`) и укажите `template_name`.
* **Если нужна своя группировка или сложная логика (1 файл Python):**
  1. Создайте `apps/production/reports/<report_name>.py`:
     ```python
     from .registry import BaseStationReport, ReportContext, register_report

     @register_report('glazing', label='דו"ח זיגוג')
     class GlazingReport(BaseStationReport):
         template_name = 'production/reports/report_glazing.html'
         include_template = 'production/includes/report_glazing.html'
         is_portrait = False

         def get_extra_context(self, ctx: ReportContext) -> dict:
             return {'glass_rows': ...}
     ```
  2. Перезапустите сервер и выберите `דו"ח זיגוג` в поле **מודול דו"ח (`report_handler`)** станции в админке.

### Рецепт 3: Добавить нестандартный кастомизатор со своей логикой
* **Обычный кастомизатор** (фурнитура, подмена материала `bom_overrides`, SVG-пресет, ЧПУ-макрос, доп. станция): настраивается целиком в админке, **0 строк кода**.
* **Необычная математика или правила (1 файл Python):**
  1. Создайте `apps/production/engine/plugins/<plugin_name>.py` и переопределите только нужные хуки (`on_init`, `on_geometry`, `on_before_bom`, `on_bom`, `on_hardware`, `on_routing`, `on_visuals`):
     ```python
     from .registry import BaseCustomizerPlugin, register_customizer

     @register_customizer('MY_FEATURE', label='שם הפלאגין בעברית')
     class MyFeaturePlugin(BaseCustomizerPlugin):
         priority = 50

         def on_geometry(self, state, gc, cache) -> None:
             ...
     ```
  2. Перезапустите сервер и выберите плагин в поле **פלאגין עיבוד (`plugin_code`)** у `Customizer` в админке.

---

## 4. Карта файлов проекта

### `apps/accounts/`
| Файл | Назначение |
| :--- | :--- |
| `models.py` | Кастомный `User` с ролями (`ADMIN`, менеджеры и т.д., свойство `is_admin_user`). |

### `apps/catalog/` — Коммерческий каталог
| Файл | Назначение |
| :--- | :--- |
| `models.py` | `ProductType`, `ProductFamily`, `Series`, `Front` (`finish_type`), `ProductModel` (`required_customizers`, `parent_model`, `effective_bom`), `Color`, `Material`, `Hardware`, `MachiningFeature`, `Customizer` (`tag`, `plugin_code`, `bom_overrides`, `outward_replacement`, `par1..par5`). |
| `admin.py` | Админка каталога (`django-unfold`), инлайны `BOMInline` / `ProductEngineeringRule`, динамический выбор `plugin_code` из `CustomizerPluginRegistry`. |
| `serializers.py`, `views.py`, `urls.py` | DRF-сериализаторы и API каталога для динамических форм заказа. |

### `apps/engineering/` — Инженерные правила, BOM, маршруты, ЧПУ и SVG
| Файл | Назначение |
| :--- | :--- |
| `schemas.py` | Pydantic-схемы `EngineeringRulesConfig`, `CncLimitsConfig`, `CutCoefficientsConfig` + функция глубокого слияния `deep_merge_rules`. |
| `models/rules.py` | `ProductEngineeringRule` (`engineering_product_rules`) — JSON-правила геометрии/допусков + `resolve_for_product()`. |
| `models/bom.py` | `BOM` (`production_bom`) — 14 слотов материалов с `DecimalField` расхода (`*_consumption`), базовая фурнитура и пресеты SVG-пазлов. |
| `models/standards.py` | `LockStandardHeight` (с `alignment_tolerance`) и `HingeStandardHeight`. |
| `models/routing.py` | `ProductionStation` (`target_machine`, `report_handler`, `specification_type`, `alternative_station`, `is_phase1`), `ProductionRoute`, `ProductionRouteStep`, `CustomizerProductionStation`. |
| `models/cnc.py` | `PerimeterRoutingFile` (`edge_shape`), `HardwareMacroFile`, `CustomizerMacroFile`, `FrontEngravingFile`. |
| `models/puzzles.py` | `SvgPattern`, `PuzzleBlockPrototype`, `PuzzlePreset`, `CustomizerPuzzleMapping`. |
| `admin.py` | Админка инженерных моделей, JSON-редактор, динамические списки `target_machine` (`MachineRegistry`) и `report_handler` (`ReportRegistry`) на `ProductionStation`. |

### `apps/orders/` — Заказы, группы, позиции и складская накладная
| Файл | Назначение |
| :--- | :--- |
| `models.py` | `Order`, `OrderChangeLog`, `OrderItemsGroup` (вкл. `is_split_installation`, `is_special_detail`), `OrderItemsGroupCustomizer`, `OrderItem`, `GroupSpecification` + `GroupSpecificationCustomizer`, `OrderWarehouseItem`. |
| `services.py` | `recalculate_item_marks(order)` и `sync_group_items(group)`. |
| `forms.py`, `serializers.py`, `admin.py`, `views.py`, `urls.py`, `utils.py` | Карточка заказа, CRUD групп/позиций, API спецификаций, расчёт рабочих дней Израиля. |

### `apps/production/` — Производство, ядро, плагины, ЧПУ, наклейки и отчёты

```text
apps/production/
├── apps.py                          # автозагрузка cnc, reports и engine.plugins при старте
├── registry_utils.py                # autodiscover_package() на базе pkgutil (пропускает registry, base, common, library)
├── models.py                        # OrderSpecificationSnapshot, DoorLabel, ItemStationProgress, StationScanAuditLog, OrderStationNote, StationDailySheetLog
├── services.py                      # OrderProductionService (жизненный цикл) и ProductionDataService (ZIP, фильтрация, делегирование в reports/)
├── views.py / urls.py               # запуск фаз, замеры, station_report (ReportRegistry), трекинг, склад, BarTender write-back, sync_usb, cnc-library
├── cnc_views.py                     # веб-интерфейс конструктора библиотек ЧПУ (/production/cnc-library/, только is_staff)
├── warehouse_service.py             # WarehousePackingSlipService (накладная склада через dry-run OrderSpecEngine)
├── tracking_services.py             # StationTrackingService (очереди станков, обработка сканов)
├── order_tracking_service.py        # OrderTrackingService (обзор заказа, аномалии, действия диспетчера)
├── usb_sync.py                      # синхронизация файлов ЧПУ на USB
├── management/
│   └── commands/
│       └── build_cnc_library.py     # CLI-команда пересборки библиотек ЧПУ (dry-run / dir / zip / фильтры)
├── engine/
│   ├── __init__.py                  # публичный фасад ядра
│   ├── schemas.py                   # ProductionSpec, OrderSpec, SpecBOMItem (с sku), DoorPuzzleSpec
│   ├── cache.py                     # OrderReferenceCache (1 загрузка справочников на заказ, 0 N+1)
│   ├── evaluator.py                 # безопасный AST-вычислитель формул SVG
│   ├── runner.py                    # OrderSpecEngine (линейный поток: 6 калькуляторов + хуки плагинов + align_batch + наклейки)
│   ├── spec_gateway.py              # TechnicalSpecService и OrderValidationError поверх OrderSpecificationSnapshot
│   ├── validation.py                # OrderValidationService (dry-run валидация заказа)
│   ├── calculators/
│   │   ├── base.py                  # ItemRuntimeState, валидация проёма, Appearance, формат кастомизаторов
│   │   ├── geometry.py              # внутренний проём, полотна, пресс-заготовки (0.5 см), раскрой листов
│   │   ├── bom.py                   # материал коробки, bom_overrides, подбор листов, SpecBOMItem
│   │   ├── hardware.py              # замок, WC/CYLINDER/KEY, цилиндр, ручка, петли, высоты + align_batch_lock_heights
│   │   ├── routing.py               # edge_shape, станции маршрута, лимиты Essepigi, is_special_detail -> ACCORD_CUSTOM (type=2)
│   │   └── visuals.py               # DoorPuzzleSpec и applied_presets
│   └── plugins/
│       ├── registry.py              # BaseCustomizerPlugin, CustomizerPluginRegistry, @register_customizer
│       ├── double_door.py           # DOUBLE_DOOR (priority=10)
│       ├── wood_edge.py             # WOOD_EDGE (priority=20)
│       └── casing.py                # CASING (priority=50)
├── labels/
│   └── generator.py                 # DoorLabelGenerator (однопроходная сборка, см -> мм, делегирует QR в MachineRegistry)
├── cnc/
│   ├── __init__.py                  # экспорт реестра и инструментов библиотек
│   ├── registry.py                  # MachineContext, BaseMachineDriver, MachineRegistry, @register_machine
│   ├── library.py                   # LibraryBuildScope, LibraryBuildResult, MachineLibraryService, render_cnc_template, safe_path_segment
│   ├── essepigi.py                  # ESSEPIGI
│   ├── accord_std.py                # ACCORD_STD
│   ├── accord_custom.py             # ACCORD_CUSTOM
│   └── mecal.py                     # MECAL (XML-файлы заказа)
└── reports/
    ├── registry.py                  # ReportContext, BaseStationReport, ReportRegistry, @register_report
    ├── common.py                    # prepare_grouped_data, enrich_report_doors_spec, enrich_report_frames_spec
    ├── generic.py                   # generic (обработчик по умолчанию для простых табличных станций)
    ├── press.py                     # press (заготовки + SVG-пазлы)
    ├── wood_frames.py               # wood_frames (4-уровневая группировка деревянных коробок)
    ├── alum_frames.py               # alum_frames
    ├── alum_doors.py                # alum_doors
    ├── cut_sheets.py                # cut_sheets
    ├── facing.py                    # facing (облицовки с эскизами)
    └── warehouse.py                 # warehouse (накладная склада + сводка фурнитуры)
```

### `templates/` и `static/`
| Путь | Назначение |
| :--- | :--- |
| `static/js/order_details.js` | Интерактив карточки заказа, каскадные селекты, покраска, переключатель `is_special_detail`, сохранённые спецификации. |
| `templates/orders/includes/group_modal.html`, `group_card.html` | Форма создания/редактирования группы и карточка группы (вкл. `פרט מיוחד` и `התקנה מפוצלת`). |
| `templates/orders/includes/reports_modal.html` | Модалка печати отчётов по батчам и станциям + USB-синхронизация. |
| `templates/production/cnc_library_builder.html` | Веб-интерфейс генерации, Dry-Run предпросмотра и скачивания ZIP-библиотек ЧПУ. |
| `templates/production/reports/` и `includes/` | Автономные печатные отчёты и подключаемые секции Master Print. |

---

## 5. Статус рефакторинга (Завершён)

* [x] **Этап 1:** Подготовка и зачистка базовых артефактов.
* [x] **Этап 2:** Выделение приложения `apps/engineering` без потери данных + `ProductEngineeringRule`.
* [x] **Этап 3А:** Миграция конструктива/допусков (в положительные см), `DecimalField` в BOM, чистка `catalog` и `engineering`.
* [x] **Этап 3Б:** Чистка `orders`, переход на `OrderSpecificationSnapshot`, добавление `is_special_detail`, вынос `apps/orders/services.py`.
* [x] **Этап 4:** Замена 27-шагового пайплайна на линейный `OrderSpecEngine`, `OrderReferenceCache` (0 N+1) и однопроходный `DoorLabelGenerator`.
* [x] **Этап 5А:** Модульный реестр станков ЧПУ `apps/production/cnc/` (`MachineRegistry`).
* [x] **Этап 5Б:** Модульный реестр отчётов станций `apps/production/reports/` (`ReportRegistry`) + динамические списки в админке.
* [x] **Этап 5В:** Модульный реестр плагинов кастомизаторов `apps/production/engine/plugins/` (`CustomizerPluginRegistry`) + `Customizer.plugin_code`.
* [x] **Этап 5Г:** UI для `פרט מיוחד`, удаление временных реэкспортов из `apps/production/models.py`, финальная документация.
* [x] **Этап 5Д:** Каркас потокового генератора библиотек ЧПУ (`cnc/library.py`, CLI `build_cnc_library`, Web UI `/production/cnc-library/`).