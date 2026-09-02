import csv
import requests
from io import StringIO
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.catalog.models import ProductType, ProductFamily, Series, Front, ProductModel, Customizer
from apps.orders.models import Order, OrderItemsGroup, OrderItem

SPREADSHEET_ID = "1wRkpaS-v47ChK_AAnncRw7ctw0rDOcbQBpWzsEvXWJc"

SHEET_GIDS = {
    "product_type": "0",
    "product_family": "1019533299",
    "series": "8873469",
    "fronts": "1391627999",
    "product_model": "962906250",
    "customizers": "1591898175",
    "orders": "2028635400",
    "order_items_group": "1895688750",
    "order_items": "219516140",
}

class Command(BaseCommand):
    help = "Reset database and populate from Google Sheets"

    def handle(self, *args, **options):
        self.stdout.write("Starting database reset...")

        with transaction.atomic():
            # Delete in order of dependencies (reverse of creation)
            self.stdout.write("Cleaning up existing data...")
            OrderItem.objects.all().delete()
            OrderItemsGroup.objects.all().delete()
            Order.objects.all().delete()
            Customizer.objects.all().delete()
            ProductModel.objects.all().delete()
            Front.objects.all().delete()
            ProductFamily.objects.all().delete()
            Series.objects.all().delete()
            ProductType.objects.all().delete()

            # 1. ProductType
            self.import_sheet("product_type", self.import_product_types)
            # 2. ProductFamily
            self.import_sheet("product_family", self.import_product_families)
            # 3. Series
            self.import_sheet("series", self.import_series)
            # 4. Fronts
            self.import_sheet("fronts", self.import_fronts)
            # 5. ProductModel
            self.import_sheet("product_model", self.import_product_models)
            # 6. Customizers
            self.import_sheet("customizers", self.import_customizers)
            # 7. Orders
            self.import_sheet("orders", self.import_orders)
            # 8. OrderItemsGroup
            self.import_sheet("order_items_group", self.import_order_items_groups)
            # 9. OrderItems
            self.import_sheet("order_items", self.import_order_items)

        self.stdout.write(self.style.SUCCESS("Database reset and population complete!"))

    def get_csv_data(self, gid):
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
        response = requests.get(url)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return csv.DictReader(StringIO(response.text))

    def import_sheet(self, sheet_key, import_func):
        self.stdout.write(f"Importing {sheet_key}...")
        url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={SHEET_GIDS[sheet_key]}"
        response = requests.get(url)
        response.raise_for_status()
        
        # Ensure we use UTF-8 encoding for Hebrew and other characters
        response.encoding = 'utf-8'
        
        if response.text.lstrip().startswith("<!DOCTYPE html>"):
            self.stdout.write(self.style.ERROR(f"Error: Received HTML instead of CSV for {sheet_key}. Is the spreadsheet public?"))
            return

        f = StringIO(response.text)
        reader = csv.DictReader(f)
        # Normalize headers to lowercase
        reader.fieldnames = [name.lower() for name in reader.fieldnames]
        import_func(reader)

    def import_product_types(self, reader):
        for row in reader:
            if not row.get('name'): continue
            ProductType.objects.update_or_create(
                id=row.get('id'),
                defaults={
                    'code': row.get('code'),
                    'name': row.get('name'),
                    'description': row.get('description', ''),
                    'active': str(row.get('active', 'True')).lower() == 'true'
                }
            )

    def import_product_families(self, reader):
        for row in reader:
            if not row.get('name'): continue
            ProductFamily.objects.update_or_create(
                id=row.get('id'),
                defaults={
                    'product_type_id': row.get('product_type') or row.get('product_type_id'),
                    'name': row.get('name'),
                    'code': row.get('code'),
                    'description': row.get('description', ''),
                    'active': str(row.get('active', 'True')).lower() == 'true'
                }
            )

    def import_series(self, reader):
        for row in reader:
            if not row.get('name'): continue
            Series.objects.update_or_create(
                id=row.get('id'),
                defaults={
                    'code': row.get('code'),
                    'name': row.get('name'),
                    'description': row.get('description', ''),
                    'active': str(row.get('active', 'True')).lower() == 'true'
                }
            )

    def import_fronts(self, reader):
        for row in reader:
            if not row.get('name'): continue
            Front.objects.update_or_create(
                id=row.get('id'),
                defaults={
                    'series_id': row.get('series') or row.get('series_id'),
                    'name': row.get('name'),
                    'code': row.get('code', ''),
                    'description': row.get('description', ''),
                    'active': str(row.get('active', 'True')).lower() == 'true'
                }
            )

    def import_product_models(self, reader):
        seen = set()
        for row in reader:
            if not row.get('code'): continue
            family_id = row.get('product_family') or row.get('product_family_id')
            series_id = row.get('series') or row.get('series_id')
            
            key = (family_id, series_id)
            if key in seen:
                self.stdout.write(self.style.WARNING(f"Skipping duplicate ProductModel for family {family_id} and series {series_id}"))
                continue
            seen.add(key)
            
            ProductModel.objects.update_or_create(
                product_family_id=family_id,
                series_id=series_id,
                defaults={
                    'id': row.get('id'),
                    'code': row.get('code'),
                    'name': row.get('name'),
                    'description': row.get('description', ''),
                    'active': str(row.get('active', 'True')).lower() == 'true',
                }
            )

    def import_customizers(self, reader):
        for row in reader:
            if not row.get('code'): continue
            Customizer.objects.create(
                id=row.get('id'),
                code=row.get('code'),
                name=row.get('name'),
                description=row.get('description', ''),
                active=str(row.get('active', 'True')).lower() == 'true',
                product_type_id=row.get('product_type_id') or None,
                product_family_id=row.get('product_family_id') or None,
                product_model_id=row.get('product_model_id') or None,
                tag=row.get('tag', ''),
                priority=int(row.get('priority', 100)) if row.get('priority') else 100,
                par1_label=row.get('par1_label', ''),
                par1_value=row.get('par1_value', ''),
                par1_hint=row.get('par1_hint', ''),
                par2_label=row.get('par2_label', ''),
                par2_value=row.get('par2_value', ''),
                par2_hint=row.get('par2_hint', ''),
                par3_label=row.get('par3_label', ''),
                par3_value=row.get('par3_value', ''),
                par3_hint=row.get('par3_hint', ''),
                par4_label=row.get('par4_label', ''),
                par4_value=row.get('par4_value', ''),
                par4_hint=row.get('par4_hint', '')
            )

    def import_orders(self, reader):
        for row in reader:
            if not row.get('order_number'): continue
            Order.objects.create(
                id=row.get('id'),
                order_number=row.get('order_number'),
                customer=row.get('customer', ''),
                status=row.get('status', 'NEW'),
                start_date=row.get('start_date') or None,
                painting_completion_date=row.get('painting_completion_date') or row.get('painting_date') or None,
                completion_date=row.get('completion_date') or None,
                series=row.get('series', ''),
                front=row.get('front', ''),
                color_panels=row.get('color_panels', ''),
                color_frames=row.get('color_frames', ''),
                comments=row.get('comments', '')
            )

    def import_order_items_groups(self, reader):
        for row in reader:
            if not row.get('order_id'): continue
            # Prevent OrderItemsGroup.save() from creating default items
            # because we will import them from the 'order_items' sheet.
            group = OrderItemsGroup(
                id=row.get('id'),
                order_id=row.get('order_id'),
                quantity=int(row.get('quantity', 1)) if row.get('quantity') else 1,
                product_id=row.get('product') or row.get('product_id'),
                series=row.get('series', ''),
                front=row.get('front', ''),
                color_panels=row.get('color_panels', ''),
                color_frames=row.get('color_frames', ''),
                is_split_installation=str(row.get('is_split_installation', 'False')).lower() == 'true',
                comments=row.get('comments', '')
            )
            # Use a flag or context to skip item generation if possible, 
            # but since we don't have one in the model yet, we manually delete them.
            group.save()
            group.items.all().delete()
            # self.stdout.write(f"  Saved group {group.id}")

    def import_order_items(self, reader):
        for row in reader:
            group_id = row.get('group') or row.get('group_id')
            if not group_id or not str(group_id).strip(): 
                continue
            
            # Check if id is provided and not empty
            item_id = row.get('id')
            if not item_id or not str(item_id).strip():
                continue

            # self.stdout.write(f"  Creating item {item_id} for group {group_id}")
            OrderItem.objects.create(
                id=item_id,
                group_id=group_id,
                mark=row.get('mark', ''),
                width=int(row.get('width')) if row.get('width') and str(row.get('width')).isdigit() else None,
                height=int(row.get('height')) if row.get('height') and str(row.get('height')).isdigit() else None,
                wall=int(row.get('wall')) if row.get('wall') and str(row.get('wall')).isdigit() else None,
                direction=row.get('direction', ''),
                opening=row.get('opening', ''),
                addition_cut=row.get('addition_cut', ''),
                place=row.get('place', ''),
                comment=row.get('comment', ''),
                custom_lock_height=row.get('custom_lock_height') or None,
                custom_hinge1=row.get('custom_hinge1') or None,
                custom_hinge2=row.get('custom_hinge2') or None,
                custom_hinge3=row.get('custom_hinge3') or None,
                custom_hinge4=row.get('custom_hinge4') or None,
                custom_hinge5=row.get('custom_hinge5') or None,
            )
