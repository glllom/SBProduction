# SBProduction — Архитектура и справочник проекта

**Домен:** ERP / MES-система для производства дверей (Израиль, интерфейс на иврите RTL).  
**Стек:** Django 6.x, Django REST Framework, django-unfold (админка), Pydantic v2, Bootstrap 5 + Vanilla JS, BarTender
(печать наклеек из БД), ЧПУ-станки Essepigi и Accord (WoodWOP / `.pgmx`).

---

## 1. Ключевые архитектурные правила и инварианты

1. **Строгое направление зависимостей (без циклов):**
   ```text
   accounts
   catalog  <--  engineering  <--  orders  <--  production
   catalog — чистые коммерческие справочники (без инженерных формул и ЧПУ).

    engineering — инженерные правила, BOM, стандарты высот, маршруты, ЧПУ-макросы, SVG-пазлы.
    
    orders — заказы, группы, позиции, шаблоны групп, накладная склада. Запрещено импортировать apps.production.services из apps.orders (нумерация и синхронизация позиций вынесены в apps/orders/services.py).
    
    production — расчётное ядро, снимки спецификаций, генерация наклеек, печатные отчёты, трекинг станций, расчёт склада.
    
    Единая система единиц измерения:
    
    Всё внутри БД, ProductEngineeringRule и ProductionSpec хранится строго в положительных сантиметрах (см): габариты проёма (width, height, width_bottom, wall), зазоры (leaf_top_clearance, leaf_bottom_clearance, leaf_side_clearance), вычеты коробки (frame_inner_*_reduction), толщины полотна и деревянного канта (2.0 / 1.7 / 1.0 см), припуск на пресс (press_allowance), лимиты станка Essepigi, высоты замка и петель.
    
    Отрицательное значение допустимо только для lock_height (означает привязку от низа двери вместо верха) и double_leaf_overlap.
    
    Перевод см × 10 → мм происходит ровно в одном месте — в генераторе наклеек apps/production/labels/generator.py при формировании данных для BarTender/ЧПУ.
    
    Высота на коробке (lock_height_on_frame, hinge_heights_on_frame) = высота на полотне + leaf_top_clearance (если замок от верха).
    
    Единые источники правды:
    
    Геометрия и допуски модели: engineering.ProductEngineeringRule (JSON, валидируется через EngineeringRulesConfig). Иерархия слияния: ProductFamily → parent_model → ProductModel.
    
    Обязательные кастомизаторы: catalog.ProductModel.required_customizers (с наследованием от parent_model). Поля Customizer.is_required и BOM.required_customizers удалены.
    
    Снимки спецификаций: только production.OrderSpecificationSnapshot через TechnicalSpecService (apps/production/engine/spec_gateway.py). Поля Order.phase1_spec_cache и Order.phase2_spec_cache удалены.
    
    Цвета полотна: везде пара полей color_panel_outside, color_panel_inside и флаг is_door_inside_different_color (включая Order, OrderItemsGroup и GroupSpecification). Поле color_panels удалено.
    
    Специальные бизнес-правила производства:
    
    Раздельный монтаж (is_split_installation): заказ проходит PHASE1_PRODUCTION (коробки) → PHASE1_READY (замер на объекте, ввод внутренних проёмов и высот от верха коробки) → PHASE2_PRODUCTION (полотна).
    
    Батчи (волны запуска): группы в заказе запускаются волнами (batch_number = 1, 2, ..., дата фиксации batch_date). Редактирование группы обычным менеджером разрешено в статусах NEW/WAITING или в день запуска (batch_date == today).
    
    Трапеция (OrderItem.width_bottom): для расчёта заготовки на пресс, раскроя листов, подбора листов BOM и проверки габаритных лимитов Essepigi всегда используется max(width, width_bottom).
    
    Типы наклеек DoorLabel.LabelType:
    
    0 (PRE_ROUGHING) — первичная обрезка периметра (создаётся только при скрытом деревянном канте).
    
    1 (ROUGHING) — финишная обработка периметра.
    
    2 (FINISHING) — фрезеровка под фурнитуру, замки, гравировка.
    
    Флаг פרט מיוחד (OrderItemsGroup.is_special_detail): переводит в режим ACCORD_CUSTOM (QR-путь C:\Ww8\PROJECTS\{order_num}\d{mark}.pgmx) только наклейку 2 (FINISHING). Наклейки 0 и 1 идут по обычной маршрутизации.

2. Поток данных (Production Flow)
   Order + OrderItemsGroup + OrderItem
   │
   ▼
   TechnicalSpecService.get_or_build_spec(order, phase, batch_number)
   └─ проверяет OrderSpecificationSnapshot (если нет / force_rebuild -> запускает движок)
   │
   ▼
   OrderSpecEngine.execute(order, items, phase, save_labels)
   ├─ 0. OrderReferenceCache.load_for_order(...)   [1 загрузка всех справочников, 0 N+1]
   ├─ 1. calculators/base.py (валидация, DoubleDoor, WoodEdge см, Appearance, отчетные кастомизаторы)
   ├─ 2. calculators/geometry.py (внутренний проём, полотна, пресс-заготовки шаг 0.5 см, раскрой)
   ├─ 3. calculators/bom.py (материал коробки, bom_overrides, CASING, листы, SpecBOMItem + SKU)
   ├─ 4. calculators/hardware.py (замок, WC/CYLINDER/KEY, цилиндр, ручка, петли, высоты)
   ├─ 5. calculators/routing.py (edge_shape, станции, лимиты Essepigi, is_special_detail -> type=2 ACCORD_CUSTOM)
   ├─ 6. calculators/visuals.py (SVG-пазл и applied_presets для отчёта пресса)
   ├─ 7. align_batch_lock_heights (выравнивание высот замков внутри батча по alignment_tolerance)
   └─ 8. DoorLabelGenerator (однопроходная генерация и bulk-запись DoorLabel при phase2 и 0 ошибок)
   │
   ▼
   OrderSpecificationSnapshot (JSON)  ──► Отчёты станций (HTML/Master Print)
   ──► StationTrackingService (очереди станков)
   ──► WarehousePackingSlipService (накладная склада)
   DoorLabel (SQL таблица)            ──► BarTender (печать наклеек + write-back print_count)

3. Карта файлов проекта

apps/accounts/ФайлНазначениеmodels.pyКастомный User с ролями (ADMIN, менеджеры и т.д., свойство is_admin_user)
.apps/catalog/ — Коммерческий каталог (без инженерных формул)ФайлНазначениеmodels.pyProductType, ProductFamily
(структурные флаги has_door, has_frame, has_handle, allowed_direction, supports_split_installation), Series, Front
(finish_type), ProductModel (required_customizers, parent_model, effective_bom), Color, Material (common_name,
outward_substitute, length/width), Hardware (role, rule_tag, common_name, components, machining_feature),
MachiningFeature, Customizer (tag, bom_overrides, outward_replacement, параметры par1..par5).admin.pyАдминка каталога
(django-unfold), инлайн BOMInline из apps.engineering.serializers.pyDRF-сериализаторы каталога для динамических форм
заказа.views.py, urls.pyAPI-эндпоинты каталога (серии, фронты, рамки, доступные кастомизаторы).apps/engineering/ —
Инженерные правила, BOM, маршруты, ЧПУ и SVGФайлНазначениеschemas.pyPydantic-схемы EngineeringRulesConfig,
CncLimitsConfig, CutCoefficientsConfig + функция глубокого слияния
deep_merge_rules.models/rules.pyProductEngineeringRule (таблица engineering_product_rules) — JSON-правила
геометрии/допусков на уровне ProductFamily и ProductModel + resolve_for_product().models/bom.pyBOM (db_table=
'production_bom') — 14 слотов материалов с DecimalField расхода (*_consumption), базовая фурнитура (lock, hinges,
additional) и пресеты SVG-пиктограмм.models/standards.pyLockStandardHeight (с alignment_tolerance) и
HingeStandardHeight.models/routing.pyProductionStation (target_machine, specification_type, alternative_station,
is_phase1), ProductionRoute, ProductionRouteStep, CustomizerProductionStation.models/cnc.pyPerimeterRoutingFile
(edge_shape), HardwareMacroFile (machining_feature, label_name), CustomizerMacroFile,
FrontEngravingFile.models/puzzles.pySvgPattern, PuzzleBlockPrototype, PuzzlePreset,
CustomizerPuzzleMapping.admin.pyАдминка всех инженерных моделей с JSON-редактором для правил и пазлов.apps/orders/ —
Заказы, группы, позиции и складская накладнаяФайлНазначениеmodels.pyOrder (статусы OrderStatus, даты, цвета, состояние
накладной склада warehouse_state/version), OrderChangeLog, OrderItemsGroup (production_state, batch_number, batch_date,
цвета, is_split_installation, is_special_detail), OrderItemsGroupCustomizer, OrderItem (размеры в см, width_bottom,
ручные высоты, sketch), GroupSpecification + GroupSpecificationCustomizer,
OrderWarehouseItem.services.pyrecalculate_item_marks(order) и sync_group_items(group) — вынесены из production для
разрыва циклических зависимостей.forms.pyOrderForm, OrderItemsGroupForm (вкл. is_special_detail и RBAC-блокировки после
grace-period), OrderItemForm, OrderItemsGroupCustomizerForm.serializers.pyDRF-сериализаторы кастомизаторов группы и
GroupSpecification (customizer_is_required вычисляется из ProductModel.get_required_customizers()).admin.pyАдминка
заказов, групп, позиций, логов изменений и сохранённых спецификаций.views.py, urls.py, utils.pyКарточка заказа, CRUD
групп/позиций, API спецификаций, расчёт рабочих дней Израиля (add_israeli_working_days).apps/production/ — Производство,
расчётное ядро, наклейки, отчёты, склад, трекингФайлНазначениеmodels.pyОперационные модели: OrderSpecificationSnapshot,
DoorLabel, ItemStationProgress, StationScanAuditLog, OrderStationNote, StationDailySheetLog.engine/__init__.pyПубличный
экспорт расчётного ядра (OrderSpecEngine, TechnicalSpecService, OrderValidationError, OrderSpec, ProductionSpec)
.engine/schemas.pyТипизированные Pydantic-схемы ProductionSpec, OrderSpec, SpecBOMItem (с sku), DoorPuzzleSpec,
SvgPuzzleBlock, SpecCustomizerReport.engine/cache.pyOrderReferenceCache — единовременная предзагрузка всех справочников
на заказ (0 N+1 запросов).engine/evaluator.pyБезопасный AST-вычислитель математических формул для SVG-блоков (поддержка
Decimal, min/max/round/abs).engine/runner.pyOrderSpecEngine — линейный запуск 6 калькуляторов + выравнивание замков +
вызов генератора наклеек.engine/spec_gateway.pyTechnicalSpecService и OrderValidationError — шлюз к
OrderSpecificationSnapshot.engine/calculators/base.pyItemRuntimeState, базовая валидация, DoubleDoor, WoodEdge (в см),
Appearance, форматирование кастомизаторов.engine/calculators/geometry.pyВнутренний проём, полотна
(одинарные/двойные/трапеция), заготовки на пресс (round_press_dimension, шаг 0.5 см), раскрой
листов.engine/calculators/bom.pyРазрешение материала коробки (outward_substitute), патчи bom_overrides и CASING, подбор
листов под max(w, w_bottom), сборка SpecBOMItem.engine/calculators/hardware.pyПодбор замка, режима (WC/CYLINDER/KEY),
цилиндра, ручки, петель, расчёт высот на полотне/коробке и
align_batch_lock_heights.engine/calculators/routing.pyedge_shape, станции маршрута, лимиты Essepigi (в см), правило
is_special_detail → ACCORD_CUSTOM только для наклейки 2.engine/calculators/visuals.pyСборка DoorPuzzleSpec и
applied_presets для отчёта пресса.labels/generator.py(Этап 4Б) Однопроходная генерация DoorLabel и QR-кодов
(единственное место перевода см × 10 → мм).engine/validation.py(Этап 4Б) OrderValidationService — проверки готовности
заказа к запуску и отчётам.services.pyOrderProductionService (жизненный цикл запуска/завершения фаз) и
ProductionDataService (подготовка данных для HTML-отчётов и ZIP).warehouse_service.pyWarehousePackingSlipService —
автосборка и пересчёт накладной фурнитуры склада (OrderWarehouseItem) на базе холостого прогона
OrderSpecEngine.tracking_services.pyStationTrackingService — инициализация маршрута позиций, обработка сканов
штрих-кодов, очереди станков.order_tracking_service.pyДетальный трекинг заказа, поиск аномалий (обход станций), ручные
действия диспетчера.views.py, urls.pyЗапуск в производство, ввод замеров после Фазы 1, единая точка отчётов
station_report, пресс, облицовки, деревянные коробки, сравнение снимков, склад, дашборд трекинга, write-back BarTender,
USB-синк.usb_sync.pyСинхронизация ЧПУ-файлов с USB-носителем.templates/ и
static/ПутьНазначениеstatic/js/order_details.jsИнтерактив карточки заказа, каскадные селекты, покраска (вкл.
color_panel_outside/inside), сохранённые спецификации.templates/orders/includes/reports_modal.htmlМодалка печати отчётов
по батчам и станциям.templates/production/reports/Автономные печатные отчёты (master_report.html, report_press.html,
report_wood_frames.html, report_facing.html, report_warehouse_hardware.html, split_measurer_report.html,
daily_stations_sheets.html).templates/production/includes/Подключаемые секции отчётов для Master Print
(report_alum_doors.html, report_alum_frames.html, report_cut_sheets.html, report_press.html, report_wood_frames.html,
report_facing.html, report_warehouse_hardware.html).

4. Статус рефакторинга (Roadmap)
   [x] Этап 1: Подготовка и чистка базовых артефактов.

   [x] Этап 2: Выделение приложения apps/engineering (перенос 15 моделей state-only миграцией без потери данных +
   создание ProductEngineeringRule).

   [x] Этап 3А: Data-миграция конструктива/допусков (в положительные см), cut_coefficients и required_customizers;
   перевод BOM.*_consumption на DecimalField (удалён eval()); чистка catalog и engineering.BOM.

   [x] Этап 3Б: Чистка orders (удалены OrderComponentSelection и Order.*_spec_cache, починен GroupSpecification,
   добавлен is_special_detail, вынесен apps/orders/services.py); перевод production на OrderSpecificationSnapshot;
   удалены устаревшие HTML/CSV-наклейки.

   [x] Этап 4А: Созданы engine/schemas.py, engine/cache.py, engine/evaluator.py и 6 линейных калькуляторов в
   engine/calculators/.

   [ ] Этап 4Б (в работе): engine/runner.py + engine/spec_gateway.py (готовы) → осталось: labels/generator.py,
   engine/validation.py, переключение services.py/warehouse_service.py/tracking_services.py и удаление старых
   pipeline.py, bom_calculator.py, label_services.py, schemas.py, evaluator.py.

   [ ] Этап 5: Рефакторинг отчётных хелперов (ProductionDataService) и UI для флага פרט מיוחד в шаблоне карточки заказа.
