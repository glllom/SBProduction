from enum import Enum
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(str, Enum):
    ADMIN = 'ADMIN'
    USER = 'USER'

    @classmethod
    def choices(cls):
        return [
            (cls.ADMIN.value, 'Administrator'),
            (cls.USER.value, 'Standard User / Manager'),
        ]


class User(AbstractUser):
    """Custom User model with role-based access control."""
    role = models.CharField(
        'User Role',
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.USER
    )

    @property
    def is_admin_user(self) -> bool:
        return self.role == UserRole.ADMIN or self.is_superuser

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'