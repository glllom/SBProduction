from django.db import migrations, models


def copy_flags_to_families(apps, schema_editor):
    ProductFamily = apps.get_model('catalog', 'ProductFamily')
    ProductType = apps.get_model('catalog', 'ProductType')
    for product_type in ProductType.objects.all():
        ProductFamily.objects.filter(product_type_id=product_type.id).update(
            has_door=product_type.has_door,
            has_frame=product_type.has_frame,
        )


def copy_flags_to_types(apps, schema_editor):
    ProductFamily = apps.get_model('catalog', 'ProductFamily')
    ProductType = apps.get_model('catalog', 'ProductType')
    for product_type in ProductType.objects.all():
        family = ProductFamily.objects.filter(product_type_id=product_type.id).order_by('id').first()
        if family is None:
            continue
        product_type.has_door = family.has_door
        product_type.has_frame = family.has_frame
        product_type.save(update_fields=['has_door', 'has_frame'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0052_hardware_is_warehouse_item'),
        ('orders', '0048_alter_order_handle'),
    ]

    operations = [
        migrations.AddField(
            model_name='productfamily',
            name='has_door',
            field=models.BooleanField(default=True, verbose_name='יש דלת'),
        ),
        migrations.AddField(
            model_name='productfamily',
            name='has_frame',
            field=models.BooleanField(default=True, verbose_name='יש משקוף'),
        ),
        migrations.RunPython(copy_flags_to_families, copy_flags_to_types),
        migrations.RemoveField(
            model_name='producttype',
            name='has_door',
        ),
        migrations.RemoveField(
            model_name='producttype',
            name='has_frame',
        ),
    ]
