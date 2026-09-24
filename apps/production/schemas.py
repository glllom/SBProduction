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

    # Additional
    frames_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)
    doors_report_customizers: List[SpecCustomizerReport] = Field(default_factory=list)

    # Context/Metadata
    context: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class OrderSpec(BaseModel):
    """
    Complete order specification containing order info and all item specs.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    order: OrderHeaderSpec
    items: List[ProductionSpec]

class OrderSpecBatchContainer(BaseModel):
    """
    Container for partitioned specifications (batches / waves).
    e.g. {"batch_1": OrderSpec, "batch_2": OrderSpec}
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    batches: Dict[str, OrderSpec] = Field(default_factory=dict)

    def get_all_items(self) -> List[ProductionSpec]:
        """Collects items from all batches in chronological order."""
        res = []
        for batch_key in sorted(self.batches.keys()):
            res.extend(self.batches[batch_key].items)
        return res

    def get_aggregated_spec(self, order) -> OrderSpec:
        """Returns unified OrderSpec containing all items across all batches."""
        return OrderSpec(
            order=OrderHeaderSpec(
                number=str(order.order_number or ""),
                customer=order.customer or "",
                status=order.status
            ),
            items=self.get_all_items()
        )
