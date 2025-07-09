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
    EMAIL_HOBBY_CREDITS = 2

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
    credits = models.PositiveIntegerField(
        default=EMAIL_HOBBY_CREDITS, verbose_name="Credits"
    )

    objects = CustomIDManager()

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if not self.id.startswith("u_"):
            raise ValueError("User ID must start with 'u_'")
        super().save(*args, **kwargs)

    def deployed_apps_by_user(self):
        return DeployedApp.objects.filter(owner=self).values_list("id", flat=True)


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


class EmailUsage(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name="User",
        on_delete=models.PROTECT,
        related_name="emails",
    )
    app = models.ForeignKey(
        DeployedApp,
        verbose_name="Deployed app",
        on_delete=models.PROTECT,
        related_name="email_usage_by_app",
    )
    date = models.DateField(db_index=True, verbose_name="Date")
    sent_count = models.PositiveIntegerField(default=0, verbose_name="Sent count")
    failed_count = models.PositiveIntegerField(default=0, verbose_name="Failed count")
    read_count = models.PositiveIntegerField(default=0, verbose_name="Read count")

    class Meta:
        unique_together = ("app", "date")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.app.id} - {self.date}"


class Provider(models.Model):
    class ProviderType(models.TextChoices):
        MAILERSEND = "MAILERSEND", "MAILERSEND"
        SMTP2GO = "SMTP2GO", "SMTP2GO"

    name = models.CharField(max_length=255, unique=True, verbose_name="Provider name")
    provider_type = models.CharField(max_length=20, choices=ProviderType.choices)
    credentials_format = models.JSONField(default=dict)
    master_credentials = models.JSONField(
        null=False, blank=False, verbose_name="Master credentials"
    )


class AppSendingConfiguration(models.Model):
    class ProvisioningStatusChoices(models.TextChoices):
        IDLE = "idle", "Idle"
        PENDING = "pending", "Pending"
        ERROR = "error", "Error"
        SUCCESS = "success", "Success"

    app = models.ForeignKey(
        DeployedApp,
        on_delete=models.CASCADE,
        related_name="app_smtp_credentials",
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="user_smtp_credentials"
    )
    provider = models.ForeignKey(
        Provider, on_delete=models.CASCADE, related_name="provider_smtp_credentials"
    )
    credentials = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True, verbose_name="Active")
    provisioning_status = models.CharField(
        max_length=20,
        choices=ProvisioningStatusChoices.choices,
        default=ProvisioningStatusChoices.IDLE,
        verbose_name="Provisioning creds status",
    )
    provisioning_error = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["app", "user"],
                condition=models.Q(is_active=True),
                name="unique_active_app_user_config",
            )
        ]

    def __str__(self):
        return f"{self.app.id} -> {self.provider.name} ({'Active' if self.is_active else 'Inactive'})"


class SentEmailLog(models.Model):
    class EmailStatusChoices(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        QUEUED = "queued", "Queued"
        DELIVERED = "delivered", "Delivered"
        BOUNCED = "bounced", "Bounced"
        OPENED = "opened", "Opened"

    app = models.ForeignKey(
        DeployedApp, on_delete=models.CASCADE, related_name="sent_emails_by_app"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sent_emails_by_user"
    )
    provider = models.CharField(max_length=50, verbose_name="Provider")
    time_sent = models.DateTimeField(auto_now_add=True, verbose_name="Time sent")
    status = models.CharField(
        max_length=20,
        choices=EmailStatusChoices.choices,
        default=EmailStatusChoices.QUEUED,
        verbose_name="Status",
    )
    time_read = models.DateTimeField(null=True, blank=True, verbose_name="Time read")
    to_email = models.CharField(max_length=255, verbose_name="Recipient email")
    subject = models.CharField(max_length=255, verbose_name="Subject", blank=True)
    message_id = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Message ID"
    )
    message_tag = models.CharField(
        max_length=255, blank=True, null=True, verbose_name="Message tag", unique=True
    )
    error_message = models.TextField(
        blank=True, null=True, verbose_name="Error message"
    )

    class Meta:
        ordering = ["-time_sent"]

    def __str__(self):
        return f"{self.app.id} to {self.to_email} at {self.time_sent} [{self.status}]"
