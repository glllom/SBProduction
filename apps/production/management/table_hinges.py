import os

import django

# Указываем путь к вашему файлу настроек Django (замените 'SBProduction.settings' на ваш актуальный модуль настроек, если он называется иначе)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SBProduction.settings')
django.setup()

from decimal import Decimal

from django.db import transaction

from catalog.models import ProductFamily, Hardware
from production.models import HingeStandardHeight


def import_hinge_standards():
    REGULAR_HINGE_ID = 4  # סמום_11סמ (Cemom_11)
    HEAVY_HINGE_ID = 2  # אוטלב 190 (otlav190)
    family_ids = [1, 2]

    # Структура данных: (hardware_id, min_height, max_height, [список базовых высот], [опциональный список для 4 петель])
    hinges_data = [
        # --- 196-200 ---
        (REGULAR_HINGE_ID, 196, 200, [Decimal('15'), Decimal('75'), Decimal('160')], None),
        (HEAVY_HINGE_ID, 196, 200, [Decimal('160'), Decimal('75'), Decimal('15')], None),

        # --- 201-205 ---
        (REGULAR_HINGE_ID, 201, 205, [Decimal('15'), Decimal('75'), Decimal('115'), Decimal('170')], None),

        # --- 211-215 ---
        (REGULAR_HINGE_ID, 211, 215, [Decimal('15'), Decimal('75'), Decimal('115'), Decimal('180')], None),
        (HEAVY_HINGE_ID, 211, 215, [Decimal('15'), Decimal('75'), Decimal('170')], None),

        # --- 221-225 ---
        (REGULAR_HINGE_ID, 221, 225, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('190')], None),
        (HEAVY_HINGE_ID, 221, 225, [Decimal('180'), Decimal('45'), Decimal('15')],
         [Decimal('15'), Decimal('45'), Decimal('180')]),

        # --- 231-235 ---
        (REGULAR_HINGE_ID, 231, 235, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('200')], None),
        (HEAVY_HINGE_ID, 231, 235, [Decimal('190'), Decimal('45'), Decimal('15')], None),

        # --- 241-245 ---
        (REGULAR_HINGE_ID, 241, 245, [Decimal('15'), Decimal('45'), Decimal('115'), Decimal('210')], None),
        (HEAVY_HINGE_ID, 241, 245, [Decimal('200'), Decimal('45'), Decimal('15')], None),

        # --- 251-255 ---
        (REGULAR_HINGE_ID, 251, 255, [Decimal('15'), Decimal('45'), Decimal('125'), Decimal('220')], None),
        (HEAVY_HINGE_ID, 251, 255, [Decimal('210'), Decimal('45'), Decimal('15')], None),

        # --- 261-265 ---
        (REGULAR_HINGE_ID, 261, 265, [Decimal('15'), Decimal('45'), Decimal('135'), Decimal('230')],
         [Decimal('15'), Decimal('45'), Decimal('135'), Decimal('220')]),
        (HEAVY_HINGE_ID, 261, 265, [Decimal('220'), Decimal('135'), Decimal('45'), Decimal('15')], None),

        # --- 271-275 ---
        (REGULAR_HINGE_ID, 271, 275, [Decimal('15'), Decimal('45'), Decimal('145'), Decimal('240')],
         [Decimal('15'), Decimal('45'), Decimal('145'), Decimal('230')]),
        (HEAVY_HINGE_ID, 271, 275, [Decimal('230'), Decimal('145'), Decimal('45'), Decimal('15')], None),

        # --- 281-285 ---
        (REGULAR_HINGE_ID, 281, 285, [Decimal('15'), Decimal('155'), Decimal('45'), Decimal('250')],
         [Decimal('15'), Decimal('155'), Decimal('45'), Decimal('240')]),
        (HEAVY_HINGE_ID, 281, 285, [Decimal('240'), Decimal('155'), Decimal('45'), Decimal('15')], None),

        # --- 291-295 ---
        (REGULAR_HINGE_ID, 291, 295, [Decimal('15'), Decimal('45'), Decimal('105'), Decimal('165'), Decimal('260')],
         None),
        (HEAVY_HINGE_ID, 291, 295, [Decimal('250'), Decimal('165'), Decimal('45'), Decimal('15')], None),
    ]

    with transaction.atomic():
        # 1. Полная очистка старых данных
        deleted_count, _ = HingeStandardHeight.objects.all().delete()
        print(f"Удалено старых записей: {deleted_count}")

        families = list(ProductFamily.objects.filter(id__in=family_ids))
        if not families:
            print("Ошибка: Семейства продуктов с ID 1 и 2 не найдены!")
            return

        created_records = 0

        for hardware_id, min_h, max_h, vals_base, vals_opt in hinges_data:
            hardware_obj = Hardware.objects.filter(id=hardware_id).first()
            if not hardware_obj:
                print(f"Предупреждение: Фурнитура с ID {hardware_id} не найдена.")
                continue

            # Создаем базовую запись
            base_values = {f"value{i + 1}": vals_base[i] for i in range(len(vals_base))}
            standard_base = HingeStandardHeight.objects.create(
                min_height=Decimal(str(min_h)),
                max_height=Decimal(str(max_h)),
                **base_values
            )
            standard_base.product_families.set(families)
            standard_base.hinges.add(hardware_obj)
            created_records += 1

            # Если есть опциональный набор (например, под дополнительную петлю)
            if vals_opt:
                opt_values = {f"value{i + 1}": vals_opt[i] for i in range(len(vals_opt))}
                standard_opt = HingeStandardHeight.objects.create(
                    min_height=Decimal(str(min_h)),
                    max_height=Decimal(str(max_h)),
                    **opt_values
                )
                standard_opt.product_families.set(families)
                standard_opt.hinges.add(hardware_obj)
                created_records += 1

        print(f"Успешно создано записей стандартов высот петель: {created_records}")


if __name__ == '__main__':
    import_hinge_standards()
