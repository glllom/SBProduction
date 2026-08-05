import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'SBProduction.settings')
django.setup()

from django.apps import apps

print("Data check:")
for model in apps.get_app_config('catalog').get_models():
    count = model.objects.count()
    if count > 0:
        print(f"Model {model.__name__}: {count} records")
        for obj in model.objects.all()[:3]:
            # Try to print name or code if they exist
            name = getattr(obj, 'name', 'N/A')
            code = getattr(obj, 'code', 'N/A')
            try:
                # We try to encode to utf-8 and then print hex to verify what is actually stored
                name_bytes = name.encode('utf-8')
                print(f"  - {code}: {name_bytes.hex(' ')}")
            except Exception as e:
                print(f"  - {code}: Error {e}")
