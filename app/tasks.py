import logging

from celery import shared_task
from django.db import transaction

from .models import AppSendingConfiguration
from .services.user_service import UserService
from .smtp_provider import get_provider_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_email_task(self, app_id: str, user_id: str, to: str, subject: str, html: str):
    """
    Celery task to send email asynchronously.

    Args:
        app_id: The ID of the app sending the email
        to: Recipient email address
        subject: Email subject
        html: Email HTML content
        user_id: The ID of the user who owns the app
    """
    from app.services.email_service import EmailService

    try:
        config = AppSendingConfiguration.objects.get(app_id=app_id, is_active=True)
    except AppSendingConfiguration.DoesNotExist:
        raise Exception("No active sending configuration found for this app.")

    provider_client = get_provider_client(
        config.provider.provider_type, config.provider.master_credentials
    )

    email_data = {
        "to": to,
        "subject": subject,
        "html": html,
        "from_email": config.credentials.get("from_email"),
        "app_id": app_id,
        "user_id": user_id,
    }

    success = provider_client.send_email(config.credentials, email_data)

    if not success:
        EmailService.update_email_usage(app_id=app_id, user_id=user_id, status="FAIL")
        raise Exception("Failed to send email via SMTP")

    EmailService.update_email_usage(app_id=app_id, user_id=user_id, status="SENT")
    UserService.deduct_user_credits(app_id, user_id)

    logger.info(
        "Email sent successfully from %s to %s via %s",
        app_id,
        to,
        config.provider.provider_type,
    )
    return True


def switch_app_provider(app_id: str, user_id: str, provider_id: int) -> bool:
    with transaction.atomic():
        AppSendingConfiguration.objects.filter(app_id=app_id, is_active=True).update(
            is_active=False
        )
        AppSendingConfiguration.objects.update_or_create(
            app_id=app_id,
            provider_id=provider_id,
            defaults={"is_active": True, "user_id": user_id, "credentials": {}},
        )
        return True


@shared_task
def set_app_provider_task(app_id: str, user_id: str, provider_id: int) -> bool:
    logger.info(
        "Setting email provider %s for app_id %s, user_id %s",
        provider_id,
        app_id,
        user_id,
    )
    try:
        switch_app_provider(app_id, user_id, provider_id)
        return True
    except Exception as e:
        logger.error("Failed to set app provider: %s", e, exc_info=True)
        raise


@shared_task
def provision_credentials_for_app_task(
    app_id: str, owner_id: str, provider_id: int
) -> bool:
    logger.info("Provisioning credentials for app %s", app_id)
    try:
        app_data = {"id": app_id, "owner_id": owner_id}
        config = AppSendingConfiguration.objects.get(
            app_id=app_id, provider_id=provider_id, is_active=True
        )
        client = get_provider_client(
            config.provider.provider_type, config.provider.master_credentials
        )
        credentials = client.provision_credentials_for_app(app_data)
        if credentials:
            config.credentials = credentials
            config.provisioning_status = (
                AppSendingConfiguration.ProvisioningStatusChoices.SUCCESS
            )
            config.provisioning_error = None
            config.save(
                update_fields=[
                    "credentials",
                    "provisioning_status",
                    "provisioning_error",
                ]
            )
        logger.info(
            "Provisioned credentials for app %s with provider %s",
            app_id,
            config.provider.provider_type,
        )
        return True
    except Exception as e:
        config.provisioning_status = (
            AppSendingConfiguration.ProvisioningStatusChoices.ERROR
        )
        config.provisioning_error = str(e)
        config.save(update_fields=["provisioning_status", "provisioning_error"])
        logger.error("Error in provision_credentials_for_app: %s", e, exc_info=True)
        return False
