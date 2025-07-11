from datetime import date

from app.models import AppSendingConfiguration, EmailUsage
from app.services.user_service import UserService
from app.tasks import send_email_task


class InsufficientCreditsError(Exception):
    pass


class NoActiveSendingConfigError(Exception):
    pass


class EmailService:
    @staticmethod
    def update_email_usage(app_id: str, user_id: str, status: str):
        usage, _ = EmailUsage.objects.get_or_create(
            app_id=app_id, user_id=user_id, date=date.today()
        )
        if status == "FAIL":
            usage.failed_count += 1
        elif status == "SENT":
            usage.sent_count += 1
        usage.save(update_fields=["failed_count", "sent_count"])

    @staticmethod
    async def send_email(app_id: str, user_id: str, to: str, subject: str, html: str):
        try:
            config = await AppSendingConfiguration.objects.aget(
                app_id=app_id, is_active=True
            )
        except AppSendingConfiguration.DoesNotExist:
            raise NoActiveSendingConfigError
        credit_check = await UserService.check_user_credits(user_id)
        if not credit_check:
            raise InsufficientCreditsError
        else:
            send_email_task.delay(app_id, user_id, to, subject, html)
