from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class SpecBOMItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
    
    type: str
    section: str
    item_name: str
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
    params: List[SpecCustomizerParam] = Field(default_factory=list)

class OrderHeaderSpec(BaseModel):
    """
    General order information for the specification header.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    number: str
    customer: str
    status: str

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
    addition_cut: Optional[float] = None

    # Opening parameters
    direction: str = ""  # L/R (localized)
    opening: str = ""    # In/Out (localized)
    direction_code: str = "" # L/R
    opening_code: str = ""   # IN/OUT

    # Appearance
    front_name: str = ""
    color_panels: str = ""
    color_frames: str = ""
    basic_color_frames: str = ""
    frame_paint_option: str = ""
    panel_paint_option: str = ""
    handle_name: str = ""

    # Technical data
    cnc_program: str = ""
    tech_notes: str = ""
    sketch_url: str = ""

    # Hardware and machining
    lock_name: str = Field("", alias="lock")
    lock_height: Optional[float] = Field(None, alias="lock's height")
    hinge_name: str = Field("", alias="hinges")
    hinge_heights: List[float] = Field(default_factory=list, alias="hinges height")

    # Bill of Materials (BOM)
    frame: str = "" # Formerly 'frame' in TechnicalSpec dataclass
    bom_items: List[SpecBOMItem] = Field(default_factory=list)
    profiles: List[str] = Field(default_factory=list)

    # Additional
    frames_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    
    # Context/Metadata
    context: Dict[str, Any] = Field(default_factory=dict)

class OrderSpec(BaseModel):
    """
    Complete order specification containing order info and all item specs.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    order: OrderHeaderSpec
    items: List[ProductionSpec]
