from django.core.exceptions import ValidationError
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from apps.engineering.schemas import EngineeringRulesConfig, deep_merge_rules


class ProductEngineeringRule(models.Model):
    """
    Типизированный JSON конструктива.
    Задаётся либо на уровне ProductFamily (базовые правила),
    либо на уровне ProductModel (только отличия от семейства).
    """
    product_family = models.OneToOneField(
        'catalog.ProductFamily',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='engineering_rule',
        verbose_name='משפחת מוצרים',
    )
    product_model = models.OneToOneField(
        'catalog.ProductModel',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='engineering_rule',
        verbose_name='דגם מוצר',
    )
    rules = models.JSONField(
        'כללי הנדסה וגיאומטריה (JSON)',
        default=dict,
        blank=True,
        help_text='מידות ומרווחים בס"מ (ערכים חיוביים). בדגם מוצר יש להזין רק חריגות ממשפחת המוצרים.',
    )

    class Meta:
        db_table = 'engineering_product_rules'
        verbose_name = 'כלל הנדסי למוצר'
        verbose_name_plural = 'כללים הנדסיים למוצרים'

    def __str__(self):
        if self.product_model_id:
            return f"כלל לדגם: {self.product_model.name}"
        if self.product_family_id:
            return f"כלל למשפחה: {self.product_family.name}"
        return f"כלל הנדסי #{self.pk}"

    def clean(self):
        super().clean()
        if bool(self.product_family_id) == bool(self.product_model_id):
            raise ValidationError("יש לבחור משפחת מוצרים או דגם מוצר (בדיוק אחד מהם).")

        raw_rules = self.rules or {}
        if not isinstance(raw_rules, dict):
            raise ValidationError({'rules': "שדה הכללים חייב להיות אובייקט JSON."})

        try:
            EngineeringRulesConfig.model_validate(raw_rules)
        except PydanticValidationError as exc:
            raise ValidationError({'rules': str(exc)})

    @classmethod
    def resolve_for_product(cls, product_model) -> EngineeringRulesConfig:
        """Собирает итоговый конструктив с наследованием: Семейство -> Модель-родитель -> Модель."""
        merged: dict = {}
        if not product_model:
            return EngineeringRulesConfig()

        family_rule = cls.objects.filter(product_family_id=product_model.product_family_id).first()
        if family_rule and family_rule.rules:
            merged = deep_merge_rules(merged, family_rule.rules)

        if product_model.parent_model_id:
            parent_rule = cls.objects.filter(product_model_id=product_model.parent_model_id).first()
            if parent_rule and parent_rule.rules:
                merged = deep_merge_rules(merged, parent_rule.rules)

        model_rule = cls.objects.filter(product_model_id=product_model.id).first()
        if model_rule and model_rule.rules:
            merged = deep_merge_rules(merged, model_rule.rules)

        return EngineeringRulesConfig.model_validate(merged)
