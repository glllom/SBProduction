from django.db import migrations, models


def populate_existing_customizer_plugins(apps, schema_editor):
    """Автоматически проставляет plugin_code существующим кастомизаторам по их tag."""
    from apps.production.engine.plugins import CustomizerPluginRegistry

    Customizer = apps.get_model('catalog', 'Customizer')
    for cust in Customizer.objects.filter(plugin_code=''):
        plugin = CustomizerPluginRegistry.resolve_for_customizer(cust)
        if plugin is not None:
            cust.plugin_code = plugin.code
            cust.save(update_fields=['plugin_code'])


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0056_alter_color_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customizer',
            name='plugin_code',
            field=models.CharField(blank=True, db_index=True, default='',
                                   help_text='מזהה פלאגין מתוך apps/production/engine/plugins (ריק = לוגיקה סטנדרטית)',
                                   max_length=64, verbose_name='פלאגין עיבוד (Plugin)'),
        ),
        migrations.RunPython(populate_existing_customizer_plugins, migrations.RunPython.noop),
    ]
