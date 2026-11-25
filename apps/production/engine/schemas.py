from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SvgPuzzleBlock(BaseModel):
    x: float
    y: float
    w: float
    h: float
    fill_type: str = "SOLID"
    fill_color: str = "#fab005"
    pattern_name: Optional[str] = None
    border_color: str = "#000000"
    border_width: float = 1.0
    border_dasharray: str = ""
    opacity: float = 1.0
    order: int = 10
    text: str = ""
    text_color: str = "#000000"
    text_x: Optional[float] = None
    text_y: Optional[float] = None
    font_size: int = 11


class DoorPuzzleSpec(BaseModel):
    face_blocks: List[SvgPuzzleBlock] = Field(default_factory=list)
    sandwich_blocks: List[SvgPuzzleBlock] = Field(default_factory=list)


class SpecBOMItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    section: str
    item_name: str
    sku: str = ""
    common_name: Optional[str] = None
    quantity: float
    tag: Optional[str] = None
    item_id: Optional[int] = None


class SpecCustomizerParam(BaseModel):
    label: str
    value: str
    is_custom: bool = False


class SpecCustomizerReport(BaseModel):
    id: Optional[int] = None
    code: Optional[str] = None
    name: str
    tag: Optional[str] = None
    params: List[SpecCustomizerParam] = Field(default_factory=list)


class OrderHeaderSpec(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    number: str
    customer: str
    status: str
    production_start_date: str = ""
    painting_completion_date: str = ""
    completion_date: str = ""


class ProductionSpec(BaseModel):
    """
    Полная техническая спецификация одной позиции заказа.
    Все линейные размеры, зазоры, толщины и высоты — строго в сантиметрах.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Identifiers
    item_id: int
    mark: str = Field(..., alias="number")
    place: str = ""
    comment: str = ""
    sketch_url: str = ""

    # Catalog
    product_name: str = Field("", alias="model_name")
    product_code: str = Field("", alias="model")
    product_family: str = ""
    series: str = ""
    has_door: bool = True
    has_frame: bool = True
    has_handle: bool = True
    is_special_detail: bool = False

    # Geometry (cm)
    height: float = 0.0
    width: float = 0.0
    width_bottom: Optional[float] = None
    wall: float = 0.0
    leaf_thickness: float = 4.0
    inner_height: float = 0.0
    inner_width: float = 0.0
    frame_inner_height_reduction: float = 0.0
    frame_inner_width_reduction: float = 0.0
    leaf_top_clearance: float = 0.0
    addition_cut: Optional[float] = None
    panel_dimensions: List[Dict[str, Optional[float]]] = Field(default_factory=list)
    press_dimensions: List[Dict[str, float]] = Field(default_factory=list)

    # Opening parameters
    direction: str = ""
    opening: str = ""
    direction_code: str = ""
    opening_code: str = ""
    is_double_door: bool = False
    edge_shape: bool = False

    # Wood edge (thickness strictly in cm)
    has_wood_edge: bool = False
    is_hidden_wood_edge: bool = False
    wood_edge_thickness: float = 0.0
    wood_edge_sides: int = 4
    wood_edge_type: str = ""

    # Appearance
    front_name: str = ""
    finish_type: str = "PAINT"
    color_frames: str = ""
    basic_color_frames: str = ""
    frame_paint_option: str = ""
    panel_paint_option: str = ""
    color_panel_outside: str = ""
    color_panel_inside: str = ""
    handle_name: str = ""

    # Cutting & BOM
    cut_coefficients: Dict[str, Any] = Field(default_factory=dict)
    cut_sheets: List[Dict[str, Any]] = Field(default_factory=list)
    frame: str = ""
    bom_items: List[SpecBOMItem] = Field(default_factory=list)
    profiles: List[str] = Field(default_factory=list)

    # Hardware & Machining (cm)
    lock_id: Optional[int] = None
    lock_name: str = Field("", alias="lock")
    lock_option_type: str = Field("", alias="lock option type")
    lock_height: Optional[float] = Field(None, alias="lock's height")
    lock_height_on_frame: Optional[float] = None
    hinge_name: str = Field("", alias="hinges")
    hinge_heights: List[float] = Field(default_factory=list, alias="hinges height")
    hinge_heights_on_frame: List[float] = Field(default_factory=list)

    # Visuals (press diagram)
    applied_presets: List[Dict[str, Any]] = Field(default_factory=list)
    puzzle_spec: Optional[DoorPuzzleSpec] = None

    # Customizers & Engraving
    frames_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    doors_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    label_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    engraving_data: Dict[str, Any] = Field(default_factory=dict)

    # Routing & CNC
    route_station_ids: List[int] = Field(default_factory=list)
    route_station_codes: List[str] = Field(default_factory=list)
    cnc_targets: Dict[int, str] = Field(default_factory=dict)

    # Validation errors
    errors: List[str] = Field(default_factory=list)


class OrderSpec(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    order: OrderHeaderSpec
    batches: Dict[str, List[ProductionSpec]] = Field(default_factory=dict)
