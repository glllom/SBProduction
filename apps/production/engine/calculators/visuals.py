import re
from typing import Any, Dict, List, Optional

from .base import ItemRuntimeState
from ..cache import OrderReferenceCache
from ..evaluator import FormulaEvaluator
from ..schemas import DoorPuzzleSpec, SvgPuzzleBlock


def calculate_visuals(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    spec = state.spec
    if state.phase == 'phase1' or not spec.has_door:
        return

    puzzle_spec = DoorPuzzleSpec()
    prototypes = cache.puzzle_prototypes

    # 1. Базовые пресеты из BOM
    bom = state.effective_bom
    if bom:
        base_params = {
            'H': spec.height,
            'W': spec.width,
            'thickness': spec.leaf_thickness,
        }
        preset_fields = ['filling_preset', 'panel_frame_preset', 'base_preset']
        if not spec.is_hidden_wood_edge:
            preset_fields.append('covering_preset')

        for field_name in preset_fields:
            preset = getattr(bom, field_name, None)
            if preset and preset.blocks_config:
                _unpack_blocks(preset.blocks_config, prototypes, puzzle_spec, base_params)

    # 2. Пресеты кастомизаторов
    for gc in state.customizers:
        c = gc.customizer
        mapping = getattr(c, 'puzzle_mapping', None)
        if not mapping or not mapping.preset or not mapping.preset.blocks_config:
            continue

        preset = mapping.preset
        params: Dict[str, Any] = {'H': float(spec.height or 0), 'W': float(spec.width or 0)}
        params_meta: Dict[str, Dict[str, Any]] = {}
        preset_labels: List[Dict[str, Any]] = []

        for i in range(1, 6):
            val_order = getattr(gc, f'par{i}', None)
            val_default = getattr(c, f'par{i}_value', None)
            str_order = str(val_order).strip() if val_order not in (None, '') else ''
            str_default = str(val_default).strip() if val_default not in (None, '') else ''

            if str_order != '':
                val = val_order
                try:
                    is_custom = float(str_order) != float(str_default) if str_default != '' else True
                except ValueError:
                    is_custom = str_order != str_default
            else:
                val = val_default
                is_custom = False

            if val is not None and str(val).strip() != '':
                val_str = str(val).strip()
                try:
                    parsed_val: Any = float(val_str)
                except ValueError:
                    parsed_val = val_str

                p_key = f'p{i}'
                params[p_key] = parsed_val
                params_meta[p_key] = {'val': parsed_val, 'is_custom': is_custom}

        params['params_meta'] = params_meta

        _unpack_blocks(preset.blocks_config, prototypes, puzzle_spec, params, labels=preset_labels)

        spec.applied_presets.append({
            'name': preset.name,
            'code': getattr(preset, 'code', ''),
            'customizer_name': c.name,
            'labels': preset_labels,
        })

    spec.puzzle_spec = puzzle_spec


def _unpack_blocks(
        blocks_config,
        prototypes: dict,
        puzzle_spec: DoorPuzzleSpec,
        params: Dict[str, Any],
        labels: Optional[list] = None,
) -> None:
    if isinstance(blocks_config, dict):
        for view_name in ('face', 'sandwich'):
            for cfg in blocks_config.get(view_name, []):
                block = _create_block(cfg, prototypes, params, labels=labels)
                if not block:
                    continue
                if view_name == 'face':
                    puzzle_spec.face_blocks.append(block)
                else:
                    puzzle_spec.sandwich_blocks.append(block)
    elif isinstance(blocks_config, list):
        for cfg in blocks_config:
            block = _create_block(cfg, prototypes, params, labels=labels)
            if not block:
                continue
            view = cfg.get('view')
            if view == 'face':
                puzzle_spec.face_blocks.append(block)
            elif view == 'sandwich':
                puzzle_spec.sandwich_blocks.append(block)


def _create_block(
        cfg: dict,
        prototypes: dict,
        params: Dict[str, Any],
        labels: Optional[list] = None,
) -> Optional[SvgPuzzleBlock]:
    proto = prototypes.get(cfg.get('component'))
    if not proto:
        return None

    x = FormulaEvaluator.evaluate(cfg.get('x', 0), params)
    y = FormulaEvaluator.evaluate(cfg.get('y', 0), params)
    w = FormulaEvaluator.evaluate(cfg.get('w', 0), params)
    h = FormulaEvaluator.evaluate(cfg.get('h', 0), params)

    raw_text = cfg.get('text', '')
    rendered_text = ''
    if raw_text:
        def _eval_match(match):
            expr = match.group(1).strip()
            try:
                res = FormulaEvaluator.evaluate(expr, params)
                return str(int(res)) if res == int(res) else str(round(res, 2))
            except Exception:
                return match.group(0)

        rendered_text = re.sub(r'\{([^}]+)}', _eval_match, str(raw_text))

    text_x_raw = cfg.get('text_x')
    text_y_raw = cfg.get('text_y')
    text_x = FormulaEvaluator.evaluate(text_x_raw, params) if text_x_raw is not None else round(x + w / 2, 2)
    text_y = FormulaEvaluator.evaluate(text_y_raw, params) if text_y_raw is not None else round(y + h / 2, 2)

    params_meta = params.get('params_meta', {})
    text_param_key = cfg.get('text_param')
    if not text_param_key and raw_text:
        for p_k in ('p1', 'p2', 'p3', 'p4', 'p5'):
            if f"{{{p_k}" in str(raw_text):
                text_param_key = p_k
                break

    is_custom = bool(params_meta.get(text_param_key, {}).get('is_custom')) if text_param_key else False
    text_color = '#dc3545' if is_custom else (cfg.get('text_color') or proto.default_text_color or '#000000')

    if rendered_text and labels is not None:
        labels.append({'text': rendered_text, 'is_custom': is_custom})

    return SvgPuzzleBlock(
        x=x,
        y=y,
        w=w,
        h=h,
        fill_type=proto.fill_type,
        fill_color=cfg.get('fill_color') or proto.fill_color,
        pattern_name=proto.pattern.name if proto.pattern else None,
        border_color=cfg.get('border_color') or proto.border_color,
        border_width=cfg.get('border_width', proto.border_width),
        opacity=cfg.get('opacity', proto.opacity),
        order=cfg.get('order', 10),
        text=rendered_text,
        text_color=text_color,
        text_x=text_x,
        text_y=text_y,
        font_size=cfg.get('font_size') or proto.default_font_size,
    )
