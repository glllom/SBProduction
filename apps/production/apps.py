"""
Конфигурация Django-приложения apps.production.

При запуске приложения (метод ready) автоматически загружает все модули
расширения (драйверы ЧПУ, отчёты станций, плагины кастомизаторов),
чтобы они зарегистрировались в соответствующих реестрах до первого HTTP-запроса.
"""

from django.apps import AppConfig


class ProductionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.production'
    verbose_name = 'ייצור'

    def ready(self) -> None:
        """Выполняет автообнаружение подключаемых модулей производства."""
        from .registry_utils import autodiscover_package

        autodiscover_package('apps.production.cnc')
        autodiscover_package('apps.production.reports')
        autodiscover_package('apps.production.cnc')
        autodiscover_package('apps.production.reports')
        autodiscover_package('apps.production.engine.plugins')
