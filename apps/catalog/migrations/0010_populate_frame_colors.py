from django.db import migrations


def populate_frame_colors(apps, schema_editor):
    Series = apps.get_model('catalog', 'Series')
    FrameColor = apps.get_model('catalog', 'FrameColor')

    series_colors = {
        'LINEA': ['לבן', 'שחור', 'אנודייז'],
        'MONOLITH': ['שחור'],
        'AQUA': ['לבן', 'שחור', 'אנודייז'],
        'FORMA': ['לבן', 'שחור', 'אנודייז'],
        'HERITAGE': ['לבן', 'שחור'],
        'CORE': ['לבן', 'שחור', 'אנודייז'],
    }

    for series in Series.objects.all():
        series_name_upper = series.name.upper()
        colors = series_colors.get(series_name_upper, ['לבן', 'שחור', 'אנודייז'])
        for color_name in colors:
            FrameColor.objects.get_or_create(
                series=series,
                name=color_name,
                defaults={'active': True}
            )


def reverse_populate(apps, schema_editor):
    FrameColor = apps.get_model('catalog', 'FrameColor')
    FrameColor.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0009_framecolor'),
    ]

    operations = [
        migrations.RunPython(populate_frame_colors, reverse_populate),
    ]
