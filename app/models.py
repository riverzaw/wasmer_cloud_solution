import re
from typing import ClassVar, Optional, Type

from django.core.exceptions import ValidationError
from django.db import models


class CustomIDManager(models.Manager):
    PREFIX_MAP: ClassVar[dict[str, str]] = {"u_": "user", "app_": "deployedapp"}

    ID_MAX_LENGTH: ClassVar[int] = 255
    ID_PATTERN: ClassVar[str] = r"^(u_|app_)[a-zA-Z0-9-]+$"

    def validate_id(self, custom_id: str) -> None:
        if not custom_id or len(custom_id) > self.ID_MAX_LENGTH:
            raise ValidationError(
                f"ID must not be empty and must be shorter than {self.ID_MAX_LENGTH} characters."
            )
        if not any(custom_id.startswith(prefix) for prefix in self.PREFIX_MAP):
            valid_prefixes = ", ".join(self.PREFIX_MAP.keys())
            raise ValidationError(
                f"ID must start with one of the prefixes: {valid_prefixes}."
            )

    def get_prefix(self, custom_id: str) -> Optional[str]:
        for prefix, model_name in self.PREFIX_MAP.items():
            if custom_id.startswith(prefix):
                return prefix
        return None

    def get_model_class(self, prefix: str) -> Type[models.Model]:
        model_name = self.PREFIX_MAP.get(prefix)
        if not model_name:
            raise ValidationError(f"Unknown prefix: '{prefix}'.")
        try:
            return self.model._meta.apps.get_model("app", model_name)
        except LookupError as e:
            raise ValidationError(f"Could not find model for prefix '{prefix}'.") from e

    def generate_id(self, prefix: str, unique_part: str) -> str:
        if prefix not in self.PREFIX_MAP:
            raise ValidationError(f"Invalid prefix: {prefix}.")
        custom_id = f"{prefix}{unique_part}"
        self.validate_id(custom_id)
        return custom_id

    def get_by_custom_id(self, custom_id):
        self.validate_id(custom_id)
        prefix = self.get_prefix(custom_id)
        if not prefix:
            raise ValidationError("Invalid ID prefix.")
        model_class = self.get_model_class(prefix)
        try:
            return model_class.objects.get(id=custom_id)
        except model_class.DoesNotExist as e:
            raise ValidationError(f"Object with ID '{custom_id}' not found.") from e


class User(models.Model):
    class Plan(models.TextChoices):
        HOBBY = "HOBBY", "Hobby"
        PRO = "PRO", "Pro"

    id = models.CharField(max_length=255, primary_key=True, verbose_name="User ID")
    username = models.CharField(
        max_length=120, unique=True, blank=False, null=False, verbose_name="Username"
    )
    plan = models.CharField(
        choices=Plan.choices, default=Plan.HOBBY, max_length=50, verbose_name="Plan"
    )

    objects = CustomIDManager()

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if not self.id.startswith("u_"):
            raise ValueError("User ID must start with 'u_'")
        super().save(*args, **kwargs)


class DeployedApp(models.Model):
    id = models.CharField(
        max_length=255, primary_key=True, verbose_name="Deployed app ID"
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="deployed_apps",
        verbose_name="App owner",
    )
    active = models.BooleanField(default=True, verbose_name="Active")

    objects = CustomIDManager()

    def __str__(self):
        return self.id

    def save(self, *args, **kwargs):
        if not self.id.startswith("app_"):
            raise ValueError("App ID must start with 'app_'")
        super().save(*args, **kwargs)
