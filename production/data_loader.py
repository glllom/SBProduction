import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SBProduction.settings')
django.setup()

from production.models import *

def delete_bom(product: str):
    product = DBProductModel.objects.get(sku=product)
    for bom in product.bom_details.all():
        bom.delete()


full_bom = {
    "mdl_4": [
        {'component': 'msh_aqua1.8x122x244', 'tag':'cover_material', 'qty': 2},
        {'component': 'msh_flex38', 'tag':'filling_material', 'qty': 1.2},
        {'component': 'mln_pine38', 'tag':'filling_material', 'qty': 10},
        {'component': 'mln_fs10219w', 'tag':'frame', 'qty': 2.5},
        {'component': 'hdw_1001', 'tag':'lock', 'qty': 1},
        {'component': 'hdw_1004', 'tag':'lock', 'qty': 1},
        {'component': 'hdw_2001', 'tag':'handle', 'qty': 1},
        {'component': 'hdw_3001', 'tag':'hinge', 'qty': 3}
    ]
}

def update_all_bom():
    for product, bom in full_bom.items():
        delete_bom(product)
        DBBomComponent.objects.bulk_create([DBBomComponent(product_model=DBProductModel.objects.get(sku=product),
                                                           DBComponent=DBComponent.objects.get(sku=component['component']),
                                                           tag=DBBomTag.objects.get(tag=component['tag']),
                                                           qty=component['qty']) for component in bom])

def add_constructions():
    wall_thickness_lst = [10, 12]
    width_lst = [i for i in range(60, 130, 10) ]
    height_lst = [200, 210, 240, 270, 300 ]
    for wall_thickness in wall_thickness_lst:
        for width in width_lst:
            for height in height_lst:
                DBComponent.objects.create(name=f"Absolute {wall_thickness}x{width}x{height}",
                                           sku=f"mcn_abs{wall_thickness}x{width}x{height}", group="absolute",
                                           width=width, length=height, thickness=wall_thickness,
                                           component_type="construction", color="white", global_type="R")
# update_all_bom()

# add_constructions()