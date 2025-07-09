import logging
from datetime import date
from sys import exc_info

from celery import shared_task
from celery.app.base import App
from django.db import transaction
from django.utils import timezone

import app

from .models import AppSendingConfiguration, DeployedApp, EmailUsage, Provider
from .smtp_provider import get_provider_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_email_task(self, app_id: str, to: str, subject: str, html: str, user_id: str):
    """
    Celery task to send email asynchronously.

    Args:
        app_id: The ID of the app sending the email
        to: Recipient email address
        subject: Email subject
        html: Email HTML content
        user_id: The ID of the user who owns the app
    """
    try:
        app_instance = DeployedApp.objects.get(id=app_id)
        owner = app_instance.owner

        try:
            config = AppSendingConfiguration.objects.get(
                app=app_instance, is_active=True
            )
        except AppSendingConfiguration.DoesNotExist:
            usage, _ = EmailUsage.objects.get_or_create(
                app=app_instance, user=owner, date=date.today()
            )
            usage.failed_count += 1
            usage.save()
            raise Exception("No active sending configuration found for this app.")

        provider_client = get_provider_client(
            config.provider.provider_type, config.provider.master_credentials
        )

        email_data = {
            "to": to,
            "subject": subject,
            "html": html,
            "from_email": config.credentials.get(
                "from_email", config.credentials.get("username", "wtest@fastmail.com")
            ),
            "app_id": app_id,
            "user_id": user_id,
        }

        success = provider_client.send_email(config.credentials, email_data)

        if not success:
            raise Exception("Failed to send email via SMTP")

        usage, _ = EmailUsage.objects.get_or_create(
            app=app_instance, user=owner, date=date.today()
        )
        usage.sent_count += 1
        usage.save()

        logger.info(
            "Email sent successfully from %s to %s via %s",
            app_id,
            to,
            config.provider.provider_type,
        )
        return True

    except Exception as exc:
        try:
            app_instance = DeployedApp.objects.get(id=app_id)
            owner = app_instance.owner
            usage, _ = EmailUsage.objects.get_or_create(
                app=app_instance, user=owner, date=date.today()
            )
            usage.failed_count += 1
            usage.save()
        except Exception as e:
            logger.error(
                "Failed to update email usage for app %s: ", app_id, e, exc_info=True
            )

        if self.request.retries < self.max_retries:
            logger.info(
                "Retrying email send for app %s to %s. Attempt %s of %s.",
                app_id,
                to,
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc)
        else:
            logger.warning(
                "Failed to send email from app %s to %s after %s attempts: %s",
                app_id,
                to,
                self.max_retries,
                exc,
            )
            raise exc


@shared_task
def send_email_with_credit_check(
    app_id: str, to: str, subject: str, html: str, user_id: str
):
    """
    Task that checks credits before sending email.
    This should be called from the GraphQL mutation.
    """
    from .models import User

    try:
        user = User.objects.get(id=user_id)
        app_instance = DeployedApp.objects.get(id=app_id)

        if user.plan == User.Plan.HOBBY:
            if user.credits <= 0:
                usage, _ = EmailUsage.objects.get_or_create(
                    app=app_instance, user=user, date=date.today()
                )
                usage.failed_count += 1
                usage.save()
                raise Exception("Insufficient credits.")

            user.credits -= 1
            user.save(update_fields=["credits"])

        send_email_task.delay(app_id, to, subject, html, user_id)

        return True

    except Exception as e:
        logger.error("Failed to queue email for app %s: %s", app_id, e, exc_info=True)
        raise e


@shared_task
def set_app_provider(app_id: str, user_id: str, provider_id: int) -> bool:
    logger.info(
        "Setting email provider %s for app_id %s, user_id %s",
        provider_id,
        app_id,
        user_id,
    )
    try:
        with transaction.atomic():
            AppSendingConfiguration.objects.filter(
                app_id=app_id, is_active=True
            ).update(is_active=False)
            try:
                existing_config = AppSendingConfiguration.objects.get(
                    app_id=app_id, provider_id=provider_id
                )
                existing_config.is_active = True
                existing_config.save()
            except AppSendingConfiguration.DoesNotExist:
                AppSendingConfiguration.objects.create(
                    app_id=app_id,
                    user_id=user_id,
                    provider_id=provider_id,
                    is_active=True,
                    credentials={},
                )
        return True
    except Exception as e:
        logger.error("Failed to set app provider: %s", e, exc_info=True)
        raise


@shared_task
def provision_credentials_for_app(app_id: str, provider_id: int) -> bool:
    logger.info("Provisioning credentials for app %s", app_id)
    try:
        app = DeployedApp.objects.get(id=app_id)
        app_data = {"id": app.id}
        provider = Provider.objects.get(id=provider_id)
        config = AppSendingConfiguration.objects.get(
            app=app, provider=provider, is_active=True
        )
        client = get_provider_client(
            provider.provider_type, provider.master_credentials
        )
        credentials = client.provision_credentials_for_app(app_data)
        if credentials:
            config.credentials = credentials
            config.provisioning_status = (
                AppSendingConfiguration.ProvisioningStatusChoices.SUCCESS
            )
            config.provisioning_error = None
            config.save()
        logger.info("Provisioned credentials for app %s", app_id)
        return True
    except Exception as e:
        config.provisioning_status = (
            AppSendingConfiguration.ProvisioningStatusChoices.ERROR
        )
        config.provisioning_error = str(e)
        logger.error("Error in provision_credentials_for_app: %s", e, exc_info=True)
        return False
