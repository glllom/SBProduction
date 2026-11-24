from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class SheetDeltaConfig(BaseModel):
    width_delta: float = 0.0
    height_delta: float = 0.0


class CutCoefficientsConfig(BaseModel):
    model_config = ConfigDict(extra='allow')

    alucobond: Optional[SheetDeltaConfig] = None
    exterior_panel: Optional[SheetDeltaConfig] = None
    interior_panel: Optional[SheetDeltaConfig] = None
    rail_delta: float = 0.0


class CncLimitsConfig(BaseModel):
    """Ограничения габаритов полотна для станков ЧПУ (в сантиметрах)."""
    essepigi_min_w: float = Field(default=60.0, ge=0)
    essepigi_max_w: float = Field(default=100.0, ge=0)
    essepigi_min_h: float = Field(default=180.0, ge=0)
    essepigi_max_h: float = Field(default=230.0, ge=0)


class EngineeringRulesConfig(BaseModel):
    """
    Единый конструктив модели/семейства.
    Все линейные размеры, зазоры и вычеты — строго в сантиметрах, положительные (>= 0).
    """
    model_config = ConfigDict(extra='forbid')

    thickness: float = Field(default=4.0, ge=0)
    frame_inner_height_reduction: float = Field(default=0.0, ge=0)
    frame_inner_width_reduction: float = Field(default=0.0, ge=0)
    leaf_top_clearance: float = Field(default=1.0, ge=0)
    leaf_bottom_clearance: float = Field(default=1.0, ge=0)
    leaf_side_clearance: float = Field(default=0.7, ge=0)
    double_leaf_overlap: float = Field(default=0.7, ge=0)
    press_allowance: float = Field(default=1.0, ge=0)

    cut_coefficients: CutCoefficientsConfig = Field(default_factory=CutCoefficientsConfig)
    cnc_limits: CncLimitsConfig = Field(default_factory=CncLimitsConfig)
    custom_params: Dict[str, Any] = Field(default_factory=dict)


def deep_merge_rules(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Рекурсивно объединяет словарь правил семейства с переопределениями модели."""
    merged = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_rules(merged[key], value)
        else:
            merged[key] = value
    return merged
