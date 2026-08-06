from django.db import models
from apps.catalog.models import ProductModel

class ProductTechnicalData(models.Model):
    """
    Техническая спецификация изделия для производства.
    Хранит параметры, необходимые для CNC станков и формирования техзаданий.
    """
    product = models.OneToOneField(
        ProductModel,
        on_delete=models.CASCADE,
        related_name='tech_data',
        verbose_name='Модель продукции'
    )
    
    cnc_program_name = models.CharField(
        'Имя программы ЧПУ',
        max_length=255,
        blank=True,
        help_text='Например: door_v1_standard.prg'
    )
    
    technical_notes = models.TextField(
        'Технические примечания',
        blank=True,
        help_text='Инструкции для работников цеха'
    )
    
    # Здесь можно добавить любые другие технические параметры
    # например, допуски, типы фрез, настройки оборудования и т.д.

    class Meta:
        verbose_name = 'Технические данные изделия'
        verbose_name_plural = 'Технические данные изделий'

    def __str__(self):
        return f"Tech data for {self.product.name}"
