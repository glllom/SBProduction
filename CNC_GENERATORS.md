# Руководство по драйверам ЧПУ и генераторам файлов (SBProduction)

Этот документ описывает, как в SBProduction устроен слой интеграции со станками ЧПУ (`apps/production/cnc/`), как добавлять новые станки и как создавать генераторы управляющих файлов и библиотек макросов **без модификации ядра системы**.

---

## 1. Три режима работы драйвера станка

Любой станок ЧПУ в системе оформляется как один класс-наследник `BaseMachineDriver`, зарегистрированный в `MachineRegistry`. Драйвер объединяет две производственные сущности — **«Инструкцию»** (под конкретную дверь/заказ) и **«Библиотеку»** (дерево макросов из справочников каталога):

| Режим | Метод драйвера | Когда вызывается | Что производит |
| :--- | :--- | :--- | :--- |
| **1. Инструкция (QR / наклейка)** *(Runtime, обязательный)* | `build_qr_payload(ctx)` | При пересчёте спецификации заказа (`DoorLabelGenerator`) | Строка QR-кода для наклейки BarTender (`0`, `1` или `2`): путь к файлу в библиотеке станка + параметры на лету |
| **2. Файлы заказа** *(Runtime, опциональный)* | `generate_files(order, specs)` | При запуске заказа / экспорте файлов ЧПУ | Словарь `{относительный_путь: bytes}` — временные файлы под конкретные позиции заказа (XML, `.pgmx`, `.mpr`, `.cix`, G-code) |
| **3. Библиотека станка** *(Build-time, опциональный)* | `supports_library = True` + `build_library(scope)` | Вручную из CLI или Web UI, когда добавлен новый замок/петля/фасад или повреждена папка на станке | Потоковый генератор `yield (относительный_путь, bytes)` — готовое дерево папок (сотни/тысячи файлов) из БД Django |

---

## 2. Где граница: «только плагин» vs «правка ядра»

### Вы пишете ТОЛЬКО плагин в `apps/production/cnc/` (0 правок в ядре), если:
* Добавляется новый станок ЧПУ со своим синтаксисом QR-кодов.
* Добавляется генерация файлов заказа (XML, PGMX, MPR, CIX, G-code, CSV).
* Добавляется или меняется генератор библиотеки макросов: структура дерева папок, правила именования, текстовые шаблоны `{{ ... }}` или сборка G-code из фрагментов.
* Требуется специфическая математика координат на основе данных, которые уже есть в `ProductionSpec` и `MachineContext`.

### Единоразовая правка ядра потребуется только в двух случаях:
1. **Нужно хранить исходный G-code прямо в админке БД:** если вы выберете подход со склейкой кусков G-code из базы данных, достаточно добавить одно текстовое поле (например, `gcode_snippet = models.TextField(blank=True, default='')`) в `apps/engineering/models/cnc.py` (`HardwareMacroFile` / `FrontEngravingFile` / `PerimeterRoutingFile`). Вся инфраструктура `LibraryBuildScope` уже умеет подгружать эти модели.
2. **Новый канал автоматической доставки на станок:** сейчас поддерживаются BarTender (SQL-таблица `DoorLabel`), скачивание ZIP из браузера, запись в локальную/сетевую папку из CLI и USB-синхронизация. Если понадобится автоотправка по FTP/REST/MQTT, транспортный адаптер добавляется один раз.

---

## 3. Структура размещения плагина (файл или мини-пакет)

Автообнаружение `apps/production/registry_utils.py` (`pkgutil.iter_modules`) при старте Django автоматически импортирует **и одиночные `.py` файлы, и папки-пакеты с `__init__.py`** внутри `apps/production/cnc/`. Пропускаются только служебные модули (`_*`, `registry`, `base`, `common`, `library`).

### Вариант А — Простой станок (один файл)
Подходит, когда станок работает только по QR или имеет небольшой генератор:
```text
apps/production/cnc/
└── biesse.py
```

### Вариант Б — Станок с шаблонами и генератором библиотеки (мини-пакет)
Подходит, когда у станка есть свои шаблоны `.pgmx.tpl` / `.mpr.tpl` / фрагменты G-code и вспомогательные модули:
```text
apps/production/cnc/
└── homag/
    ├── __init__.py          # класс HomagDriver с @register_machine('HOMAG', ...)
    ├── gcode_blocks.py      # вспомогательные функции генерации операций
    └── templates/
        ├── door_base.mpr.tpl
        └── lock_pocket.mpr.tpl
```

> **Важно:** После создания файла или пакета достаточно перезапустить сервер. Никакие `import` в других файлах прописывать не нужно, миграции БД создавать не нужно — станок сам появится в поле `target_machine` админки `ProductionStation`, в CLI `build_cnc_library --list` и в веб-интерфейсе `/production/cnc-library/`.

---

## 4. Справочник API для разработчика плагина

Все публичные классы и утилиты импортируются из одного места:

```python
from apps.production.cnc import (
    BaseMachineDriver,
    LibraryBuildScope,
    MachineContext,
    MachineLibraryService,
    MachineRegistry,
    register_machine,
    render_cnc_template,
    render_cnc_template_file,
    safe_path_segment,
)
```

### 4.1. `MachineContext` (вход в `build_qr_payload`)
Передаётся генератором наклеек `DoorLabelGenerator` для каждой наклейки (`0`, `1`, `2`):

| Поле | Тип | Единицы / примечание |
| :--- | :--- | :--- |
| `order_number` | `str` | Номер заказа |
| `item_mark` | `str` | Сквозной номер двери в заказе (`1`, `2`, ...) |
| `label_type` | `int` | `0` (`PRE_ROUGHING`), `1` (`ROUGHING`), `2` (`FINISHING`) |
| `leaf_role` | `int` | `0` (`SINGLE`), `1` (`ACTIVE`), `2` (`PASSIVE`) |
| `width_mm`, `height_mm`, `thickness_mm` | `float` | **Миллиметры** (уже конвертированы из см) |
| `edge_type` | `str` | `'STANDARD'`, `'hidden'`, `'outer'` |
| `edge_shape` | `bool` | Признак фальца/четверти |
| `cnc_program` | `str` | Имя программы периметральной обработки |
| `lock_height` | `Optional[float]` | Высота замка (см) |
| `hinge_heights` | `List[float]` | Высоты петель (см) |
| `engraving_data` | `Dict[str, Any]` | `icon_filename` и параметры `p1..p5` |
| `spec` | `ProductionSpec` | Полная спецификация позиции (если нужны доп. поля: `opening`, `direction`, `lock_name`, `hinge_name`, `front_name`, `bom_items` и т.д.) |

### 4.2. `LibraryBuildScope` (вход в `build_library`)
Единый объект фильтров для полной или частичной пересборки библиотеки напрямую из БД. Если фильтр не задан (`None`), метод возвращает все активные записи; если задан — только выбранную ветку:

* `scope.is_partial` — `True`, если включён хотя бы один фильтр.
* `scope.get_families()` — активные `catalog.ProductFamily`.
* `scope.get_models()` — активные `catalog.ProductModel` (учитывает `family_ids` и `model_ids`).
* `scope.get_locks()` — активные `catalog.Hardware` с `role='LOCK'`.
* `scope.get_hinges()` — активные `catalog.Hardware` с `role='HINGE'`.
* `scope.get_fronts()` — активные `catalog.Front` (с `select_related('series')`).
* `scope.get_customizers()` — активные `catalog.Customizer`.
* `scope.get_hardware_macros(role=None)` — `engineering.HardwareMacroFile` (учитывает `family_ids`, `lock_ids`, `hinge_ids`).
* `scope.get_perimeter_files()` — `engineering.PerimeterRoutingFile`.
* `scope.get_front_engravings()` — `engineering.FrontEngravingFile`.
* `scope.get_customizer_macros()` — `engineering.CustomizerMacroFile`.

### 4.3. Утилиты рендера и безопасности путей
* **`render_cnc_template(template_source: str, context: dict) -> str`** — рендерит строку с синтаксисом Django Templates (`{{ var }}`, `{% if %}`, `{% for %}`), но использует отдельный движок `Engine(autoescape=False)`. Спецсимволы `<`, `>`, `&`, `"` **не экранируются**, что критично для XML, PGMX и G-code.
* **`render_cnc_template_file(template_path, context: dict) -> str`** — читает UTF-8 шаблон с диска (например, `Path(__file__).parent / 'templates' / 'door.pgmx.tpl'`) и рендерит его без HTML-экранирования.
* **`safe_path_segment(value, fallback='unknown') -> str`** — очищает имя папки/файла от символов `<>:"/\|?*`, управляющих символов и крайних точек, чтобы дерево корректно открывалось на Windows-стойке ЧПУ.
* **Потоковая отдача (`yield`):** метод `build_library()` **обязан** возвращать итератор пар `(rel_path: str, content: bytes)` через `yield`. Сервис `MachineLibraryService` сразу пишет каждый файл на диск или в `SpooledTemporaryFile` (сброс на диск после 10 МБ), поэтому пересборка 5 000–20 000 файлов не перегружает оперативную память.

---

## 5. Два готовых рецепта реализации генератора библиотеки

### Подход А: Генерация из текстовых шаблонов `{{ ... }}` (как Django Templates)

Идеален для XML/PGMX/MPR/CIX файлов, где структура программы фиксирована, а внутрь подставляются параметры модели двери, замка, петли и фасада.

**1. Создайте шаблон** `apps/production/cnc/my_cnc/templates/door_program.pgmx.tpl`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Program Model="{{ family.code }}" Thickness="{{ thickness_mm }}">
  <Param Name="L" Value="2100" />
  <Param Name="W" Value="800" />
  <Operation Type="LOCK" Sku="{{ lock.sku }}" Name="{{ lock.name }}" />
  <Operation Type="HINGE" Sku="{{ hinge.sku }}" />
  {% if engraving_file %}
  <Operation Type="ENGRAVE" File="{{ engraving_file }}" />
  {% endif %}
</Program>
```

**2. Реализуйте драйвер** `apps/production/cnc/my_cnc/__init__.py`:

```python
from pathlib import Path
from typing import Iterator, Tuple

from apps.production.cnc import (
    BaseMachineDriver,
    LibraryBuildScope,
    MachineContext,
    register_machine,
    render_cnc_template_file,
    safe_path_segment,
)

TEMPLATE_PATH = Path(__file__).parent / 'templates' / 'door_program.pgmx.tpl'


@register_machine('MY_CNC_TPL', label='My CNC (תבניות)')
class MyTemplateCncDriver(BaseMachineDriver):
    supports_library = True

    def build_qr_payload(self, ctx: MachineContext) -> str:
        """Инструкция (Runtime): указывает станку путь к готовому файлу в библиотеке."""
        spec = ctx.spec
        family_dir = safe_path_segment(getattr(spec, 'product_family', 'STD'))
        lock_dir = safe_path_segment(getattr(spec, 'lock_name', 'NO_LOCK'))
        hinge_dir = safe_path_segment(getattr(spec, 'hinge_name', 'NO_HINGE'))
        front_file = safe_path_segment(getattr(spec, 'front_name', 'PLAIN'))

        prog_path = f"C:\\CNC_LIB\\{family_dir}\\{lock_dir}\\{hinge_dir}\\{front_file}.pgmx"
        return f"{prog_path}|L={ctx.height_mm:g}|W={ctx.width_mm:g}|lock={ctx.lock_height or 0:g}"

    def build_library(self, scope: LibraryBuildScope) -> Iterator[Tuple[str, bytes]]:
        """Библиотека (Build-time): потоково собирает дерево Модель/Замок/Петля/Фасад."""
        # Материализуем небольшие справочники один раз, чтобы не делать N+1 запросы в циклах
        families = list(scope.get_families())
        locks = list(scope.get_locks())
        hinges = list(scope.get_hinges())
        fronts = list(scope.get_fronts())
        engravings_by_front = {
            e.front_id: e.file_name for e in scope.get_front_engravings()
        }

        for fam in families:
            fam_seg = safe_path_segment(fam.code or fam.name)
            thickness_mm = round((fam.thickness or 4.0) * 10, 1)

            for lock in locks:
                lock_seg = safe_path_segment(lock.sku)
                for hinge in hinges:
                    hinge_seg = safe_path_segment(hinge.sku)
                    for front in fronts:
                        front_seg = safe_path_segment(front.code or front.name)
                        rel_path = f"{fam_seg}/{lock_seg}/{hinge_seg}/{front_seg}.pgmx"

                        rendered = render_cnc_template_file(TEMPLATE_PATH, {
                            'family': fam,
                            'thickness_mm': thickness_mm,
                            'lock': lock,
                            'hinge': hinge,
                            'front': front,
                            'engraving_file': engravings_by_front.get(front.id, ''),
                        })
                        yield rel_path, rendered.encode('utf-8')
```

---

### Подход Б: Модульная склейка G-code (`get_gcode(args)`)

Идеален для станков на чистом G-code / ISO, где итоговая программа собирается последовательно из независимых блоков: шапка → периметр → замок → петли → фрезеровка фасада → финал.

```python
from typing import Iterator, List, Tuple

from apps.production.cnc import (
    BaseMachineDriver,
    LibraryBuildScope,
    MachineContext,
    register_machine,
    safe_path_segment,
)


def gcode_header(program_name: str, thickness_mm: float) -> str:
    return "\n".join([
        f"; PROGRAM: {program_name}",
        f"G71 ; mm",
        f"#THICK={thickness_mm:g}",
    ])


def gcode_lock(lock) -> str:
    # Пример: берём геометрию/параметры из Hardware (par1..par3) или из словаря по SKU
    depth = lock.get_numeric_par(1) or 85.0
    return f"; LOCK {lock.sku}\nM98 P1001 D{depth:g}"


def gcode_hinge(hinge) -> str:
    return f"; HINGE {hinge.sku}\nM98 P2001"


def gcode_footer() -> str:
    return "M30\n"


@register_machine('MY_GCODE', label='My G-Code CNC')
class MyGcodeCncDriver(BaseMachineDriver):
    supports_library = True

    def build_qr_payload(self, ctx: MachineContext) -> str:
        return f"RUN;{ctx.order_number};d{ctx.item_mark};L={ctx.height_mm:g};W={ctx.width_mm:g}"

    def build_library(self, scope: LibraryBuildScope) -> Iterator[Tuple[str, bytes]]:
        families = list(scope.get_families())
        locks = list(scope.get_locks())
        hinges = list(scope.get_hinges())

        for fam in families:
            fam_seg = safe_path_segment(fam.code or fam.name)
            thickness_mm = round((fam.thickness or 4.0) * 10, 1)

            for lock in locks:
                for hinge in hinges:
                    name = f"{fam_seg}_{safe_path_segment(lock.sku)}_{safe_path_segment(hinge.sku)}"
                    rel_path = f"{fam_seg}/{safe_path_segment(lock.sku)}/{name}.nc"

                    blocks: List[str] = [
                        gcode_header(name, thickness_mm),
                        gcode_lock(lock),
                        gcode_hinge(hinge),
                        gcode_footer(),
                    ]
                    yield rel_path, "\n".join(blocks).encode('utf-8')
```

> **Совет по совместимости комбинаций:** чтобы не генерировать заведомо невозможные комбинации (например, замок от алюминиевой двери на деревянной семье), проверяйте совместимость через уже существующий метод `lock.is_compatible_with(...)` или фильтруйте по `HardwareMacroFile.door_families` из `scope.get_hardware_macros()`.

---

## 6. Как запускать и проверять генератор

### 6.1. Из командной строки (CLI `build_cnc_library`)

**Посмотреть все станки и статус поддержки библиотеки:**
```powershell
python manage.py build_cnc_library --list
```

**Dry-Run (проверить число файлов, объём и дерево путей без записи на диск):**
```powershell
python manage.py build_cnc_library MY_CNC_TPL --dry-run
```

**Полная пересборка в папку (или прямо на сетевой диск станка) с очисткой:**
```powershell
python manage.py build_cnc_library MY_CNC_TPL --output C:\CNC_Export\MyLib --clean
```

**Частичная пересборка только для нового замка (ID 12) в ZIP-архив:**
```powershell
python manage.py build_cnc_library MY_CNC_TPL --zip C:\CNC_Export\lock12_patch.zip --lock 12
```

**Доступные фильтры частичной пересборки (можно комбинировать):**
* `--family <id ...>` — `ProductFamily`
* `--model <id ...>` — `ProductModel`
* `--lock <id ...>` — `Hardware` (`role=LOCK`)
* `--hinge <id ...>` — `Hardware` (`role=HINGE`)
* `--front <id ...>` — `Front`
* `--customizer <id ...>` — `Customizer`

### 6.2. Из веб-интерфейса (только `is_staff`)

Откройте в браузере:
```text
/production/cnc-library/
```

1. Выберите станок из списка (показываются только драйверы с `supports_library = True`).
2. При необходимости выделите конкретные семьи, замки, петли или фасады (если оставить пустыми — соберётся полная библиотека).
3. Нажмите **«תצוגה מקדימה (Dry-Run)»**, чтобы увидеть итоговое количество файлов, размер в КБ/МБ и первые 50 путей дерева.
4. Нажмите **«בנה והורד ZIP»** для потоковой сборки и скачивания архива.

---

## 7. Чек-лист перед выкаткой нового драйвера в цех

1. Проверить регистрацию: `python manage.py check` и `python manage.py build_cnc_library --list` — станок виден с `library: YES`.
2. Проверить пути в `--dry-run`: нет двойных слэшей, пустых сегментов, запрещённых Windows-символов (`: * ? " < > |`) и лишнего HTML-экранирования (`&amp;`, `&lt;`, `&quot;`).
3. Сверить совпадение пути в `build_qr_payload()` (Runtime) и `build_library()` (Build-time) — QR-код с наклейки должен ссылаться ровно на тот путь, который создаёт генератор библиотеки.
4. Проверить кодировку и переводы строк: если стойка станка требует Windows CRLF (`\r\n`) или кодировку `cp1255`/`ascii` вместо `utf-8`, задайте это явно в `yield rel_path, text.replace('\n', '\r\n').encode('cp1255')`.
5. Проверить отсутствие N+1 запросов в `build_library()`: все выборки из `scope.get_*()` выносите **до** вложенных циклов `for`.