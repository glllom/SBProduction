from typing import Dict, List

from apps.engineering.models import ProductionStation
from apps.orders.models import OrderItemsGroup
from apps.production.models import DoorLabel
from .base import ItemRuntimeState
from ..cache import OrderReferenceCache


def calculate_routing(state: ItemRuntimeState, cache: OrderReferenceCache) -> None:
    if state.phase == 'phase1' or not state.group or not state.product:
        return

    spec = state.spec
    group = state.group
    limits = state.rules.cnc_limits

    # 1. Флаг edge_shape по семейству двери (нужен и наклейкам, и складу для гильотин)
    family_id = state.product.product_family_id
    perim_obj = cache.perimeter_by_family.get(family_id)
    spec.edge_shape = bool(perim_obj and perim_obj.edge_shape)

    # 2. Базовые станции маршрута (VERIFICATION -> маршрут модели -> доп. станции кастомизаторов -> PAINTING)
    base_stations: List[ProductionStation] = []
    seen_ids = set()

    def add_station(st: ProductionStation | None) -> None:
        if st and st.id not in seen_ids:
            base_stations.append(st)
            seen_ids.add(st.id)

    add_station(cache.verification_station)
    for st in cache.route_stations_by_product.get(state.product.id, []):
        add_station(st)

    forced_station_ids = set()
    for gc in state.customizers:
        for rule in cache.customizer_station_rules.get(gc.customizer_id, []):
            if rule.force_alternative_machine:
                forced_station_ids.add(rule.station_id)
            elif rule.station and rule.station.active:
                add_station(rule.station)

    needs_paint = (
            group.panel_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
            or group.frame_paint_option != OrderItemsGroup.PaintOption.NO_PAINT
    )
    if needs_paint:
        add_station(cache.painting_station)

    # 3. Проверка габаритных лимитов Essepigi (в см, с учётом трапеции)
    if spec.panel_dimensions:
        p0 = spec.panel_dimensions[0]
        w_cm = max(float(p0.get('width') or 0), float(p0.get('width_bottom') or 0))
        h_cm = float(p0.get('height') or 0)
    else:
        w_cm = max(float(spec.width or 0), float(spec.width_bottom or 0))
        h_cm = float(spec.height or 0)

    fits_essepigi = (
            not spec.is_double_door
            and (limits.essepigi_min_w <= w_cm <= limits.essepigi_max_w)
            and (limits.essepigi_min_h <= h_cm <= limits.essepigi_max_h)
    )
    forced_alt_global = bool(forced_station_ids)

    # 4. Итоговый список станций и целевых станков ЧПУ по типу наклейки (0, 1, 2)
    final_stations: List[ProductionStation] = []
    cnc_targets: Dict[int, str] = {}

    for st in base_stations:
        effective_st = st
        if st.is_label:
            needs_alt = (not fits_essepigi) or forced_alt_global or (st.id in forced_station_ids)
            if needs_alt and st.alternative_station_id:
                effective_st = st.alternative_station

            label_idx = effective_st.label_type_index
            if label_idx is not None and effective_st.target_machine:
                cnc_targets[label_idx] = effective_st.target_machine

        final_stations.append(effective_st)

    default_machine = (
        DoorLabel.TargetMachine.ESSEPIGI
        if (fits_essepigi and not forced_alt_global)
        else DoorLabel.TargetMachine.ACCORD_STD
    )
    for l_idx in (
            DoorLabel.LabelType.PRE_ROUGHING,
            DoorLabel.LabelType.ROUGHING,
            DoorLabel.LabelType.FINISHING,
    ):
        cnc_targets.setdefault(int(l_idx), default_machine)

    # 5. Флаг פרט מיוחד: переводит ТОЛЬКО наклейку 2 (FINISHING) в режим ACCORD_CUSTOM
    if spec.is_special_detail:
        cnc_targets[int(DoorLabel.LabelType.FINISHING)] = DoorLabel.TargetMachine.ACCORD_CUSTOM

    spec.route_station_ids = [s.id for s in final_stations if s and s.id]
    spec.route_station_codes = [s.code for s in final_stations if s and s.code]
    spec.cnc_targets = cnc_targets
