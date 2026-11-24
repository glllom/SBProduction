from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from django.db.models import Q

from apps.catalog.models import Customizer, Hardware, Material, ProductModel
from apps.engineering.models import (
    BOM,
    CustomizerMacroFile,
    CustomizerProductionStation,
    FrontEngravingFile,
    HardwareMacroFile,
    HingeStandardHeight,
    LockStandardHeight,
    PerimeterRoutingFile,
    ProductEngineeringRule,
    ProductionRoute,
    ProductionStation,
    PuzzleBlockPrototype,
    PuzzlePreset,
)
from apps.engineering.schemas import EngineeringRulesConfig, deep_merge_rules
from apps.orders.models import OrderItem, OrderItemsGroupCustomizer


@dataclass
class OrderReferenceCache:
    """Предзагруженные справочники на один запуск расчёта заказа (0 N+1 запросов)."""

    rules_by_product: Dict[int, EngineeringRulesConfig] = field(default_factory=dict)
    boms_by_product: Dict[int, BOM] = field(default_factory=dict)
    required_customizers_by_product: Dict[int, List[Customizer]] = field(default_factory=dict)
    customizers_by_group: Dict[int, List[OrderItemsGroupCustomizer]] = field(default_factory=dict)

    # Materials
    materials_by_id: Dict[int, Material] = field(default_factory=dict)
    materials_by_sku: Dict[str, Material] = field(default_factory=dict)
    materials_by_group_color: Dict[Tuple[str, Optional[int]], List[Material]] = field(default_factory=dict)

    # Hardware
    hardware_by_id: Dict[int, Hardware] = field(default_factory=dict)
    hardware_by_sku: Dict[str, Hardware] = field(default_factory=dict)
    hardware_by_name_role: Dict[Tuple[str, str], Hardware] = field(default_factory=dict)
    hardware_variants: Dict[Tuple[str, str, str], List[Hardware]] = field(default_factory=dict)

    # Standards
    lock_rules: Dict[Tuple[int, int], LockStandardHeight] = field(default_factory=dict)
    hinge_rules: Dict[Tuple[int, int], List[HingeStandardHeight]] = field(default_factory=dict)

    # Routing
    verification_station: Optional[ProductionStation] = None
    painting_station: Optional[ProductionStation] = None
    stations_by_id: Dict[int, ProductionStation] = field(default_factory=dict)
    route_stations_by_product: Dict[int, List[ProductionStation]] = field(default_factory=dict)
    customizer_station_rules: Dict[int, List[CustomizerProductionStation]] = field(default_factory=dict)

    # CNC macros
    perimeter_pre_roughing: Optional[PerimeterRoutingFile] = None
    perimeter_by_family: Dict[int, PerimeterRoutingFile] = field(default_factory=dict)
    hardware_macros: Dict[Tuple[int, int], List[HardwareMacroFile]] = field(default_factory=dict)
    customizer_macros: Dict[int, str] = field(default_factory=dict)
    front_engravings: Dict[int, str] = field(default_factory=dict)

    # Puzzles
    puzzle_prototypes: Dict[str, PuzzleBlockPrototype] = field(default_factory=dict)
    puzzle_presets_by_name: Dict[str, PuzzlePreset] = field(default_factory=dict)

    @classmethod
    def load_for_order(cls, order, items: List[OrderItem], phase: str = 'phase2') -> 'OrderReferenceCache':
        cache = cls()
        if not items:
            return cache

        group_ids = set()
        products_by_id: Dict[int, ProductModel] = {}
        family_ids = set()
        front_ids = set()

        if getattr(order, 'front_id', None):
            front_ids.add(order.front_id)

        for item in items:
            group = item.group
            if not group:
                continue
            group_ids.add(group.id)
            if group.front_id:
                front_ids.add(group.front_id)
            if group.product:
                products_by_id[group.product_id] = group.product
                family_ids.add(group.product.product_family_id)
                if group.product.parent_model_id:
                    family_ids.add(group.product.product_family_id)

        product_ids = set(products_by_id.keys())
        parent_ids = {p.parent_model_id for p in products_by_id.values() if p.parent_model_id}
        all_model_ids = product_ids | parent_ids

        # 1. Engineering rules (Family -> Parent -> Model)
        family_rules_map: Dict[int, dict] = {}
        model_rules_map: Dict[int, dict] = {}
        if family_ids or all_model_ids:
            rules_qs = ProductEngineeringRule.objects.filter(
                Q(product_family_id__in=family_ids) | Q(product_model_id__in=all_model_ids)
            )
            for r in rules_qs:
                if r.product_family_id:
                    family_rules_map[r.product_family_id] = r.rules or {}
                elif r.product_model_id:
                    model_rules_map[r.product_model_id] = r.rules or {}

        for pid, prod in products_by_id.items():
            merged: dict = {}
            if prod.product_family_id in family_rules_map:
                merged = deep_merge_rules(merged, family_rules_map[prod.product_family_id])
            if prod.parent_model_id and prod.parent_model_id in model_rules_map:
                merged = deep_merge_rules(merged, model_rules_map[prod.parent_model_id])
            if pid in model_rules_map:
                merged = deep_merge_rules(merged, model_rules_map[pid])
            cache.rules_by_product[pid] = EngineeringRulesConfig.model_validate(merged)

        # 2. BOMs (with parent fallback)
        raw_boms = {
            b.product_id: b
            for b in BOM.objects.filter(product_id__in=all_model_ids)
            .select_related(
                'covering', 'base', 'filling', 'panel_frame', 'casing', 'frame',
                'profile1', 'profile2', 'profile3',
                'other1', 'other2', 'other3', 'other4', 'other5',
                'lock', 'hinges',
                'filling_preset', 'panel_frame_preset', 'base_preset', 'covering_preset',
            )
            .prefetch_related('additional')
        }
        for pid, prod in products_by_id.items():
            bom = raw_boms.get(pid) or (raw_boms.get(prod.parent_model_id) if prod.parent_model_id else None)
            if bom:
                cache.boms_by_product[pid] = bom

        # 3. Required customizers per product (with parent fallback)
        if all_model_ids:
            req_map: Dict[int, List[Customizer]] = defaultdict(list)
            for prod_obj in ProductModel.objects.filter(id__in=all_model_ids).prefetch_related('required_customizers'):
                req_map[prod_obj.id] = [c for c in prod_obj.required_customizers.all() if c.active]

            for pid, prod in products_by_id.items():
                combined: Dict[int, Customizer] = {c.id: c for c in req_map.get(pid, [])}
                if prod.parent_model_id:
                    for c in req_map.get(prod.parent_model_id, []):
                        combined.setdefault(c.id, c)
                cache.required_customizers_by_product[pid] = list(combined.values())

        # 4. Group customizers
        customizer_ids = set()
        if group_ids:
            gc_qs = (
                OrderItemsGroupCustomizer.objects.filter(group_id__in=group_ids)
                .select_related(
                    'customizer',
                    'customizer__hardware',
                    'customizer__puzzle_mapping__preset',
                    'customizer__outward_replacement',
                    'customizer__outward_replacement__hardware',
                    'customizer__outward_replacement__puzzle_mapping__preset',
                )
                .prefetch_related(
                    'customizer__hardware__components',
                    'customizer__outward_replacement__hardware__components',
                )
                .order_by('customizer__tag', 'customizer__code')
            )
            grouped_gc: Dict[int, List[OrderItemsGroupCustomizer]] = defaultdict(list)
            for gc in gc_qs:
                grouped_gc[gc.group_id].append(gc)
                customizer_ids.add(gc.customizer_id)
                if gc.customizer.outward_replacement_id:
                    customizer_ids.add(gc.customizer.outward_replacement_id)
            cache.customizers_by_group = dict(grouped_gc)

        # 5. Materials (full catalog is compact; eliminates all per-door sheet/color queries)
        mats_by_gc: Dict[Tuple[str, Optional[int]], List[Material]] = defaultdict(list)
        for mat in Material.objects.select_related('color', 'outward_substitute', 'outward_substitute__color').all():
            cache.materials_by_id[mat.id] = mat
            if mat.sku:
                cache.materials_by_sku[mat.sku] = mat
            cn = (mat.common_name or '').strip()
            if cn:
                mats_by_gc[(cn, mat.color_id)].append(mat)
        for key, mat_list in mats_by_gc.items():
            mat_list.sort(key=lambda m: (float(m.length or 0), float(m.width or 0), m.id))
        cache.materials_by_group_color = dict(mats_by_gc)

        # 6. Hardware (active catalog with components & machining_feature)
        hw_variants: Dict[Tuple[str, str, str], List[Hardware]] = defaultdict(list)
        for hw in (
                Hardware.objects.filter(active=True)
                        .select_related('color', 'machining_feature')
                        .prefetch_related('components__machining_feature')
                        .order_by('id')
        ):
            cache.hardware_by_id[hw.id] = hw
            if hw.sku:
                cache.hardware_by_sku[hw.sku] = hw
            cache.hardware_by_name_role[(hw.name, hw.role)] = hw
            cn = (hw.common_name or '').strip()
            mode = (hw.par1_value or '').strip().upper()
            if cn and mode in ('WC', 'CYLINDER', 'KEY'):
                hw_variants[(hw.role, cn, mode)].append(hw)
        cache.hardware_variants = dict(hw_variants)

        # 7. Lock & Hinge standards for involved families
        if family_ids:
            for lsh in (
                    LockStandardHeight.objects.filter(product_families__id__in=family_ids)
                            .prefetch_related('product_families', 'locks')
                            .distinct()
            ):
                f_ids = [f.id for f in lsh.product_families.all() if f.id in family_ids]
                l_ids = [lk.id for lk in lsh.locks.all()]
                for fid in f_ids:
                    for lid in l_ids:
                        cache.lock_rules.setdefault((fid, lid), lsh)

            h_rules: Dict[Tuple[int, int], List[HingeStandardHeight]] = defaultdict(list)
            for hsh in (
                    HingeStandardHeight.objects.filter(product_families__id__in=family_ids)
                            .prefetch_related('product_families', 'hinges')
                            .distinct()
            ):
                f_ids = [f.id for f in hsh.product_families.all() if f.id in family_ids]
                h_ids = [hg.id for hg in hsh.hinges.all()]
                for fid in f_ids:
                    for hid in h_ids:
                        h_rules[(fid, hid)].append(hsh)
            cache.hinge_rules = dict(h_rules)

        # 8. Routing, CNC macros & Puzzles (mainly Phase 2, light enough to preload cleanly)
        if phase != 'phase1':
            for st in ProductionStation.objects.select_related('alternative_station').filter(active=True):
                cache.stations_by_id[st.id] = st
                code_up = (st.code or '').upper()
                if code_up == 'VERIFICATION' and cache.verification_station is None:
                    cache.verification_station = st
                elif code_up in ('PAINTING', 'PAINT') and cache.painting_station is None:
                    cache.painting_station = st

            if product_ids:
                for route in (
                        ProductionRoute.objects.filter(active=True, products__id__in=product_ids)
                                .prefetch_related('products', 'steps__station__alternative_station')
                                .distinct()
                ):
                    ordered_stations: List[ProductionStation] = []
                    seen_st = set()
                    for step in sorted(route.steps.all(), key=lambda s: s.order):
                        if step.station_id not in seen_st:
                            ordered_stations.append(step.station)
                            seen_st.add(step.station_id)
                    for prod in route.products.all():
                        if prod.id in product_ids:
                            cache.route_stations_by_product.setdefault(prod.id, ordered_stations)

            if customizer_ids:
                cs_rules: Dict[int, List[CustomizerProductionStation]] = defaultdict(list)
                for rule in (
                        CustomizerProductionStation.objects.filter(customizer_id__in=customizer_ids)
                                .select_related('station', 'station__alternative_station')
                                .order_by('station__order', 'id')
                ):
                    cs_rules[rule.customizer_id].append(rule)
                cache.customizer_station_rules = dict(cs_rules)

            # Perimeter routing files
            all_perimeters = list(PerimeterRoutingFile.objects.prefetch_related('doors').order_by('id'))
            if all_perimeters:
                cache.perimeter_pre_roughing = all_perimeters[0]
            for prf in all_perimeters:
                for fam in prf.doors.all():
                    if fam.id in family_ids:
                        cache.perimeter_by_family.setdefault(fam.id, prf)

            # Hardware macros
            if family_ids:
                hw_macros: Dict[Tuple[int, int], List[HardwareMacroFile]] = defaultdict(list)
                for hmf in (
                        HardwareMacroFile.objects.filter(door_families__id__in=family_ids)
                                .select_related('machining_feature')
                                .prefetch_related('hardware', 'door_families')
                                .distinct()
                ):
                    f_ids = [f.id for f in hmf.door_families.all() if f.id in family_ids]
                    hw_ids = [h.id for h in hmf.hardware.all()]
                    for fid in f_ids:
                        for hid in hw_ids:
                            hw_macros[(hid, fid)].append(hmf)
                cache.hardware_macros = dict(hw_macros)

            if customizer_ids:
                cache.customizer_macros = {
                    cmf.customizer_id: cmf.file_name.strip()
                    for cmf in CustomizerMacroFile.objects.filter(customizer_id__in=customizer_ids)
                    if cmf.file_name and cmf.file_name.strip()
                }

            if front_ids:
                cache.front_engravings = {
                    fef.front_id: fef.file_name.strip()
                    for fef in FrontEngravingFile.objects.filter(front_id__in=front_ids)
                    if fef.file_name and fef.file_name.strip()
                }

            cache.puzzle_prototypes = {
                p.code: p for p in PuzzleBlockPrototype.objects.select_related('pattern').all()
            }
            cache.puzzle_presets_by_name = {p.name: p for p in PuzzlePreset.objects.all()}

        return cache

    def find_hardware_variant(
            self,
            base_hw: Optional[Hardware],
            role: str,
            target_mode: str,
            match_color: bool = False,
    ) -> Optional[Hardware]:
        if not base_hw or not base_hw.common_name or target_mode not in ('WC', 'CYLINDER', 'KEY'):
            return base_hw

        curr_mode = (base_hw.par1_value or '').strip().upper()
        if curr_mode == target_mode:
            return base_hw

        candidates = self.hardware_variants.get((role, base_hw.common_name.strip(), target_mode), [])
        if not candidates:
            return base_hw

        if match_color and base_hw.color_id:
            for hw in candidates:
                if hw.color_id == base_hw.color_id:
                    return hw
        return candidates[0]
