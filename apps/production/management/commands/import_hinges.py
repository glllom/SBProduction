from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import ProductFamily, Hardware
from apps.production.models import HingeStandardHeight


class Command(BaseCommand):
    help = 'Импорт стандартных высот и позиций петель из таблиц'

    def handle(self, *args, **options):
        REGULAR_HINGE_ID = 4  # סמום_11סמ (Cemom_11)
        HEAVY_HINGE_ID = 2  # אוטלב 190 (otlav190)
        family_ids = [1, 2]

        hinges_data = [
            # --- 196-200 ---
            (REGULAR_HINGE_ID, 196, 200, [Decimal('15'), Decimal('75'), Decimal('160')]),
            (HEAVY_HINGE_ID, 196, 200, [Decimal('15'), Decimal('160')]),
            (HEAVY_HINGE_ID, 196, 210, [Decimal('15'), Decimal('75'), Decimal('160')]),

            # --- 201-210 ---
            (REGULAR_HINGE_ID, 201, 210, [Decimal('15'), Decimal('75'), Decimal('170')]),
            (REGULAR_HINGE_ID, 201, 210, [Decimal('15'), Decimal('75'), Decimal('115'), Decimal('170')]),

            # --- 211-220 ---
            (REGULAR_HINGE_ID, 211, 220, [Decimal('15'), Decimal('75'), Decimal('180')]),
            (REGULAR_HINGE_ID, 211, 220, [Decimal('15'), Decimal('75'), Decimal('115'), Decimal('180')]),
            (HEAVY_HINGE_ID, 211, 220, [Decimal('15'), Decimal('170')]),
            (HEAVY_HINGE_ID, 211, 220, [Decimal('15'), Decimal('75'), Decimal('170')]),

            # --- 221-230 ---
            (REGULAR_HINGE_ID, 221, 230, [Decimal('15'), Decimal('45'), Decimal('190')]),
            (REGULAR_HINGE_ID, 221, 230, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('190')]),
            (HEAVY_HINGE_ID, 221, 230, [Decimal('15'), Decimal('45'), Decimal('180')]),

            # --- 231-240 ---
            (REGULAR_HINGE_ID, 231, 240, [Decimal('15'), Decimal('45'), Decimal('200')]),
            (REGULAR_HINGE_ID, 231, 240, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('200')]),
            (HEAVY_HINGE_ID, 231, 240, [Decimal('15'), Decimal('45'), Decimal('190')]),

            # --- 241-250 ---
            (REGULAR_HINGE_ID, 241, 250, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('210')]),
            (HEAVY_HINGE_ID, 241, 250, [Decimal('15'), Decimal('45'), Decimal('200')]),

            # --- 251-260 ---
            (REGULAR_HINGE_ID, 251, 260, [Decimal('15'), Decimal('45'), Decimal('125'), Decimal('220')]),
            (HEAVY_HINGE_ID, 251, 260, [Decimal('15'), Decimal('45'), Decimal('210')]),

            # --- 261-270 ---
            (REGULAR_HINGE_ID, 261, 270, [Decimal('15'), Decimal('45'), Decimal('135'), Decimal('230')]),
            (HEAVY_HINGE_ID, 261, 270, [Decimal('15'), Decimal('45'), Decimal('220')]),
            (HEAVY_HINGE_ID, 261, 270, [Decimal('15'), Decimal('45'), Decimal('135'), Decimal('220')]),

            # --- 271-280 ---
            (REGULAR_HINGE_ID, 271, 280, [Decimal('15'), Decimal('45'), Decimal('145'), Decimal('240')]),
            (HEAVY_HINGE_ID, 271, 280, [Decimal('15'), Decimal('45'), Decimal('230')]),
            (HEAVY_HINGE_ID, 271, 280, [Decimal('15'), Decimal('45'), Decimal('145'), Decimal('230')]),

            # --- 281-290 ---
            (REGULAR_HINGE_ID, 281, 290, [Decimal('15'), Decimal('45'), Decimal('155'), Decimal('250')]),
            (HEAVY_HINGE_ID, 281, 290, [Decimal('15'), Decimal('45'), Decimal('240')]),
            (HEAVY_HINGE_ID, 281, 290, [Decimal('15'), Decimal('45'), Decimal('155'), Decimal('240')]),

            # --- 291-300 ---
            (REGULAR_HINGE_ID, 291, 300, [Decimal('15'), Decimal('45'), Decimal('165'), Decimal('260')]),
            (REGULAR_HINGE_ID, 291, 300,
             [Decimal('15'), Decimal('45'), Decimal('105'), Decimal('165'), Decimal('260')]),
            (HEAVY_HINGE_ID, 291, 300, [Decimal('15'), Decimal('45'), Decimal('250')]),
            (HEAVY_HINGE_ID, 291, 300, [Decimal('15'), Decimal('45'), Decimal('165'), Decimal('250')]),

        ]

        with transaction.atomic():
            deleted_count, _ = HingeStandardHeight.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Удалено старых записей: {deleted_count}"))

            families = list(ProductFamily.objects.filter(id__in=family_ids))
            if not families:
                self.stdout.write(self.style.ERROR("Ошибка: Семейства продуктов с ID 1 и 2 не найдены!"))
                return

            created_records = 0

            for hardware_id, min_h, max_h, vals_base in hinges_data:
                hardware_obj = Hardware.objects.filter(id=hardware_id).first()
                if not hardware_obj:
                    self.stdout.write(self.style.WARNING(f"Предупреждение: Фурнитура с ID {hardware_id} не найдена."))
                    continue

                base_values = {f"value{i + 1}": vals_base[i] for i in range(len(vals_base))}
                standard_base = HingeStandardHeight.objects.create(
                    min_height=Decimal(str(min_h)),
                    max_height=Decimal(str(max_h)),
                    **base_values
                )
                standard_base.product_families.set(families)
                standard_base.hinges.add(hardware_obj)
                created_records += 1
            self.stdout.write(self.style.SUCCESS(f"Успешно создано записей стандартов высот петель: {created_records}"))

        wood_doors_ids = [37]

        hinges_data = [
            # --- 196-200 ---
            (REGULAR_HINGE_ID, 196, 200, [Decimal('15'), Decimal('75'), Decimal('160')]),
            # --- 201-215 ---
            (REGULAR_HINGE_ID, 201, 215, [Decimal('15'), Decimal('75'), Decimal('170')]),
            # --- 216-236 ---
            (REGULAR_HINGE_ID, 216, 236, [Decimal('15'), Decimal('75'), Decimal('190')]),
        ]

        with transaction.atomic():
            families = list(ProductFamily.objects.filter(id__in=wood_doors_ids))
            if not families:
                self.stdout.write(self.style.ERROR(f"Ошибка: Семейства продуктов с ID {wood_doors_ids} не найдены!"))
                return

            created_records = 0

            for hardware_id, min_h, max_h, vals_base in hinges_data:
                hardware_obj = Hardware.objects.filter(id=hardware_id).first()
                if not hardware_obj:
                    self.stdout.write(self.style.WARNING(f"Предупреждение: Фурнитура с ID {hardware_id} не найдена."))
                    continue

                base_values = {f"value{i + 1}": vals_base[i] for i in range(len(vals_base))}
                standard_base = HingeStandardHeight.objects.create(
                    min_height=Decimal(str(min_h)),
                    max_height=Decimal(str(max_h)),
                    **base_values
                )
                standard_base.product_families.set(families)
                standard_base.hinges.add(hardware_obj)
                created_records += 1
            self.stdout.write(self.style.SUCCESS(f"Успешно создано записей стандартов высот петель: {created_records}"))
