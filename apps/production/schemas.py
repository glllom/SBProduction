from typing import Dict, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SvgPuzzleBlock(BaseModel):
    x: float
    y: float
    w: float
    h: float
    fill_type: str = "SOLID"  # SOLID или PATTERN
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
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    type: str
    section: str
    item_name: str
    common_name: Optional[str] = None
    quantity: float
    tag: Optional[str] = None
    # We might want to store the item ID or other details too
    item_id: Optional[int] = None


class SpecCustomizerParam(BaseModel):
    label: str
    value: str
    is_custom: bool = False


class SpecCustomizerReport(BaseModel):
    name: str
    tag: Optional[str] = None
    params: List[SpecCustomizerParam] = Field(default_factory=list)


class OrderHeaderSpec(BaseModel):
    """
    General order information for the specification header.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    number: str
    customer: str
    status: str
    production_start_date: str = ""
    painting_completion_date: str = ""
    completion_date: str = ""


class ProductionSpec(BaseModel):
    """
    Full technical specification for a specific item in the order.
    Used for generating reports, technical tasks, and transferring data to production.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Identifiers
    item_id: int
    mark: str = Field(..., alias="number")
    place: str = ""
    comment: str = ""

    # Catalog
    product_name: str = Field("", alias="model_name")
    product_code: str = Field("", alias="model")
    product_family: str = ""
    series: str = ""
    has_door: bool = True
    has_frame: bool = True

    # Geometry
    height: float = 0.0
    width: float = 0.0
    wall: float = 0.0
    inner_height: float = 0.0
    inner_width: float = 0.0
    frame_inner_height_reduction: float = 0.0
    frame_inner_width_reduction: float = 0.0
    leaf_top_clearance: float = 0.0
    addition_cut: Optional[float] = None
    panel_dimensions: List[Dict[str, float]] = Field(default_factory=list)

    # Opening parameters
    direction: str = ""  # L/R (localized)
    opening: str = ""  # In/Out (localized)
    direction_code: str = ""  # L/R
    opening_code: str = ""  # IN/OUT
    is_double_door: bool = False

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

    # Technical data
    cnc_program: str = ""
    tech_notes: str = ""
    sketch_url: str = ""
    cut_coefficients: Dict[str, Any] = Field(default_factory=dict)
    cut_sheets: List[Dict[str, Any]] = Field(default_factory=list)
    parts: Dict[str, Any] = Field(default_factory=dict)

    # Hardware and machining
    lock_id: Optional[int] = None
    lock_name: str = Field("", alias="lock")
    lock_option_type: str = Field("", alias="lock option type")
    lock_height: Optional[float] = Field(None, alias="lock's height")
    lock_height_on_frame: Optional[float] = None
    hinge_name: str = Field("", alias="hinges")
    hinge_heights: List[float] = Field(default_factory=list, alias="hinges height")
    hinge_heights_on_frame: List[float] = Field(default_factory=list)
    handle_type: str = Field("", alias="handle type")

    # Bill of Materials (BOM)
    frame: str = ""  # Formerly 'frame' in TechnicalSpec dataclass
    bom_items: List[SpecBOMItem] = Field(default_factory=list)
    profiles: List[str] = Field(default_factory=list)

    press_dimensions: List[Dict[str, float]] = Field(default_factory=list)
    has_wood_edge: bool = False
    is_hidden_wood_edge: bool = False
    wood_edge_thickness: float = 0.0
    wood_edge_sides: int = 4
    wood_edge_type: str = ""  # 'outer' | 'hidden'

    # Пресс и раскрой
    applied_presets: List[Dict[str, Any]] = Field(default_factory=list)
    sandwich_spec: Optional[SandwichSpec] = None
    frame_spec: Optional[FrameStructureSpec] = None
    puzzle_spec: Optional[DoorPuzzleSpec] = None

    # Additional
    frames_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    doors_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)

    # Context/Metadata
    context: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class OrderSpec(BaseModel):
    """
    Complete order specification containing order info and partitioned batches.
    e.g. {"order": {...}, "batches": {"1": [...], "2": [...]}}
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    order: OrderHeaderSpec
    batches: Dict[str, List[ProductionSpec]] = Field(default_factory=dict)


class SandwichLayerSpec(BaseModel):
    name: str  # Отображаемое имя (MDF, פלקסבורד, עופרת)
    common_name: str  # Базовый идентификатор без привязки к размеру листа
    thickness: float  # Толщина в мм (6.0, 34.0, 0.5)
    pattern_code: str = ""  # Код паттерна: 'tubular', 'foam', 'lead', 'solid'
    bg_color: str = "#e0e0e0"  # Фоновый цвет для SVG


class SandwichSpec(BaseModel):
    title: str = ""  # Текстовое описание состава: "פלקסבורד 34 + כיסוי MDF 6"
    total_thickness: float = 0.0
    layers: List[SandwichLayerSpec] = Field(default_factory=list)


class FrameStructureSpec(BaseModel):
    title: str = "אורן סטנדרט"
    is_double_perimeter: bool = False  # Двойная рамка
    has_closer: bool = False  # Закладная под верхний доводчик
    has_drop_seal: bool = False  # Скрытый порог снизу
    has_handle_reinforcement: bool = False  # Усиление под ручку-скобу
    lock_block: bool = True  # Закладная под замок (почти всегда True)
    lock_height: float = 0.0  # Высота замка для позиционирования
