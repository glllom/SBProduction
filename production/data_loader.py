import os
import sys
import django

# Добавляем корень проекта в путь поиска модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SBProduction.settings')
django.setup()

from openpyxl import load_workbook
from production.models import *
# def load_order(order_num):
#     current_order = DBOrder.objects.get(order_number=order_num)
#     print(current_order)
#     return None

def load_products():
    wb = load_workbook('sku_3.xlsx', data_only=True)
    sheets = wb.sheetnames
    types_sheet = wb[sheets[0]]
    families_sheet = wb[sheets[1]]
    products_sheet = wb[sheets[2]]
    materials_sheet = wb[sheets[3]]

    # for row in types_sheet.iter_rows(min_row=2):
        # print(row[1].value, row[2].value)
        # DBProductType.objects.create(name=row[1].value, sku=row[2].value)

    # for row in families_sheet.iter_rows(min_row=2):
    #     DBProductFamily.objects.create(name=row[1].value, sku=row[2].value, product_type=DBProductType.objects.get(id=row[3].value))

    for row in products_sheet.iter_rows(min_row=2):
        DBProductModel.objects.create(
            product_family=DBProductFamily.objects.get(sku=row[4].value),
            description=row[1].value,
            product_type=DBProductType.objects.get(sku=row[5].value),
            sku=row[2].value,
            global_type=row[3].value)

    # for row in materials_sheet.iter_rows(min_row=2):
    #     DBComponent.objects.create(
    #         name = row[0].value,
    #         width=row[1].value,
    #         length=row[2].value,
    #         thickness=row[3].value,
    #         sku=row[4].value,
    #         group=row[5].value,
    #         component_type=row[6].value,
    #         color=row[7].value,
    #         global_type=row[8].value)


load_products()




