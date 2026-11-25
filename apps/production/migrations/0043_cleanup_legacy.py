from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('production', '0042_hardwaremacrofile_label_name'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ProductTechnicalData',
        ),
        migrations.RemoveField(
            model_name='customizerpuzzlemapping',
            name='slot_action',
        ),
        migrations.RemoveField(
            model_name='customizerpuzzlemapping',
            name='target_slot',
        ),
    ]
