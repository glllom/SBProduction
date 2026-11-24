"""
Общие вспомогательные функции форматирования данных для табличных отчётов станций.

Назначение модуля:
    Вынесены из views.py и services.py, чтобы отчёты не зависели от контроллеров:
        - get_field: унифицированное чтение из Pydantic-модели или dict-снимка.
        - to_dict: преобразование ProductionSpec в обычный словарь.
        - prepare_grouped_data: группировка позиций по семейству/серии/цвету/профилю.
        - enrich_report_doors_spec: разметка show_hardware_subhead и addons_rowspan для дверей.
        - enrich_report_frames_spec: разметка show_hardware_subhead и addons_rowspan для коробок.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Унифицированно читает поле из dict или объекта (Pydantic ProductionSpec)."""
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def to_dict(item: Any) -> Dict[str, Any]:
    """Конвертирует элемент спецификации (Pydantic или dict) в копию словаря."""
    if hasattr(item, 'model_dump'):
        return item.model_dump()
    if isinstance(item, dict):
        return dict(item)
    return item.dict()


def prepare_grouped_data(items: List[Any]) -> List[Dict[str, Any]]:
    """
    Группирует плоский список позиций спецификации по основным признакам модели,
    отделки, цвета и профилей для вывода табличных отчётов.
    """
    grouped_specs: Dict[tuple, List[Any]] = {}
    for spec in items:
        key = (
            get_field(spec, 'product_family', ''),
            get_field(spec, 'series', ''),
            get_field(spec, 'product_code', ''),
            get_field(spec, 'front_name', ''),
            get_field(spec, 'basic_color_frames', ''),
            get_field(spec, 'frame_paint_option', ''),
            get_field(spec, 'color_frames', ''),
            get_field(spec, 'color_panel_outside', ''),
            tuple(get_field(spec, 'profiles', []) or []),
        )
        grouped_specs.setdefault(key, []).append(spec)

    groups_data: List[Dict[str, Any]] = []
    for key in sorted(grouped_specs.keys()):
        items_specs = grouped_specs[key]
        first = items_specs[0]

        common_front = get_field(first, 'front_name', '')
        common_color_frames = get_field(first, 'color_frames', '')
        common_color_panels = get_field(first, 'color_panel_outside', '')

        for s in items_specs[1:]:
            if get_field(s, 'front_name', '') != common_front:
                common_front = "Various"
            if get_field(s, 'color_frames', '') != common_color_frames:
                common_color_frames = "Various"
            if get_field(s, 'color_panel_outside', '') != common_color_panels:
                common_color_panels = "Various"

        group_spec = {
            'product_name': get_field(first, 'product_name', ''),
            'code': get_field(first, 'product_code', ''),
            'front_name': common_front,
            'color_frames': common_color_frames,
            'basic_color_frames': get_field(first, 'basic_color_frames', ''),
            'color_panels': common_color_panels,
            'lock_name': get_field(first, 'lock_name', ''),
            'hinge_name': get_field(first, 'hinge_name', ''),
            'common_lock_height': get_field(first, 'lock_height', ''),
            'common_hinge_heights': get_field(first, 'hinge_heights', []),
            'profiles': get_field(first, 'profiles', []),
            'frame_paint_option': get_field(first, 'frame_paint_option', ''),
            'frame': get_field(first, 'frame', ''),
            'series': get_field(first, 'series', ''),
            'product_family': get_field(first, 'product_family', ''),
            'frames_report_customizers': get_field(first, 'frames_report_customizers', []),
        }
        groups_data.append({'group_spec': group_spec, 'items_specs': items_specs})

    return groups_data


def enrich_report_doors_spec(items: List[Any]) -> List[Dict[str, Any]]:
    """
    Размечает позиции для таблицы дверных полотен:
        1. show_hardware_subhead — признак смены модели/фасада или фурнитуры.
        2. addons_rowspan — объединение подряд идущих строк с одинаковыми кастомизаторами/комментарием.
    """
    if not items:
        return []

    def _group_key(d: dict) -> tuple:
        return (d.get('product_family'), d.get('series'), d.get('front_name'))

    def _hw_key(d: dict) -> tuple:
        return (d.get('lock_name'), d.get('hinge_name'))

    def _addons_sig(d: dict) -> str:
        return json.dumps(
            {'c': (d.get('comment') or '').strip(), 'cmz': d.get('doors_report_customizers') or []},
            sort_keys=True,
            default=str,
        )

    items_data = [to_dict(it) for it in items]

    prev_key = None
    for row in items_data:
        curr_key = (_group_key(row), _hw_key(row))
        row['show_hardware_subhead'] = (curr_key != prev_key)
        prev_key = curr_key

    n = len(items_data)
    i = 0
    while i < n:
        g_key = _group_key(items_data[i])
        h_key = _hw_key(items_data[i])
        sig = _addons_sig(items_data[i])

        run_len = 1
        while (
                i + run_len < n
                and _group_key(items_data[i + run_len]) == g_key
                and _hw_key(items_data[i + run_len]) == h_key
                and _addons_sig(items_data[i + run_len]) == sig
        ):
            run_len += 1

        items_data[i]['addons_rowspan'] = run_len
        for j in range(1, run_len):
            items_data[i + j]['addons_rowspan'] = 0
        i += run_len

    return items_data


def enrich_report_frames_spec(items: List[Any]) -> List[Dict[str, Any]]:
    """
    Размечает позиции для таблицы алюминиевых коробок:
        1. show_hardware_subhead — смена профиля коробки или фурнитуры.
        2. addons_rowspan — объединение одинаковых кастомизаторов FRAMES_REPORT и комментариев.
    """
    if not items:
        return []

    def _group_key(d: dict) -> tuple:
        return (d.get('product_family'), d.get('series'), d.get('frame'))

    def _hw_key(d: dict) -> tuple:
        return (d.get('lock_name'), d.get('hinge_name'))

    def _addons_sig(d: dict) -> str:
        return json.dumps(
            {'c': str(d.get('comment') or ''), 'cmz': d.get('frames_report_customizers') or []},
            sort_keys=True,
            default=str,
        )

    items_data = [to_dict(it) for it in items]

    prev_key = None
    for row in items_data:
        curr_key = (_group_key(row), _hw_key(row))
        row['show_hardware_subhead'] = (curr_key != prev_key)
        prev_key = curr_key

    n = len(items_data)
    i = 0
    while i < n:
        g_key = _group_key(items_data[i])
        h_key = _hw_key(items_data[i])
        sig = _addons_sig(items_data[i])

        run_len = 1
        while (
                i + run_len < n
                and _group_key(items_data[i + run_len]) == g_key
                and _hw_key(items_data[i + run_len]) == h_key
                and _addons_sig(items_data[i + run_len]) == sig
        ):
            run_len += 1

        items_data[i]['addons_rowspan'] = run_len
        for j in range(1, run_len):
            items_data[i + j]['addons_rowspan'] = 0
        i += run_len

    return items_data
