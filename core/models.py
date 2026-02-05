from ctypes.wintypes import tagMSG


class Order:
    def __init__(self, customer, date_to_complete):
        self.customer = customer
        self.date_to_complete = date_to_complete
        self.items = []

class ItemInOrder:
    def __init__(self, product, width, height, direction, undercut, wall_thickness, opening):
        self.product = product
        self.panel = False
        self.frame = False
        self.width = width
        self.height = height
        self.direction = direction
        self.undercut = undercut
        self.wall_thickness = wall_thickness
        self.opening = opening
        self.panel_dimensions = (0, 0)
        self.second_panel_dimensions = None
        self.bom = []
        self.customizers = []

    def __repr__(self):
        return f"<ItemInOrder: {self.product}>"

    def __str__(self):
        return self.product.sku

    def set_panel_dimensions(self, width, height):
        self.panel_dimensions = (width, height)

class Component:
    def __init__(self, name, width, length, thickness, sku, group, component_type, color):
        self.name = name
        self.width = width
        self.length = length
        self.thickness = thickness
        self.sku = sku
        self.group = group
        self.component_type = component_type
        self.color = color

    def to_dict(self):
        return {
            "name": self.name,
            "width": self.width,
            "length": self.length,
            "thickness": self.thickness,
            "sku": self.sku,
            "group": self.group,
            "component_type": self.component_type,
            "color": self.color,
        }

class Product:
    def __init__(self, sku, description,
                 panel_reduction_width,
                 panel_reduction_height,
                 double_door_gap,
                 bom = None):
        self.sku = sku
        self.description = description
        self.panel_reduction_width = panel_reduction_width
        self.panel_reduction_height = panel_reduction_height
        self.double_door_gap = double_door_gap
        self.bom = bom

class Customizer:
    def __init__(self, name, sku, tag, par1, par1_description, par2, par3):
        self.name = name
        self.sku = sku
        self.tag = tag
        self.par1 = par1
        self.par1_description = par1_description
        self.par2 = par2
        self.par3 = par3
