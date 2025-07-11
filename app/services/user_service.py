import logging
from datetime import date

from app.models import DeployedApp, EmailUsage, User

logger = logging.getLogger(__name__)


class InsufficientCreditsError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class UserService:
    @staticmethod
    async def upgrade_account(user: User):
        user.plan = User.Plan.PRO
        await user.asave()
        return user

    @staticmethod
    async def downgrade_account(user: User):
        user.plan = User.Plan.HOBBY
        await user.asave()
        return user

    @staticmethod
    async def check_user_credits(user_id: str) -> bool:
        try:
            user = await User.objects.aget(id=user_id)
        except User.DoesNotExist:
            raise UserNotFoundError

        if user.plan == User.Plan.HOBBY:
            if user.credits <= 0:
                return False
        return True

    @staticmethod
    def deduct_user_credits(app_id: str, user_id: str) -> bool:
        try:
            user = User.objects.get(id=user_id)
            user.credits -= 1
            user.save(update_fields=["credits"])
        except User.DoesNotExist:
            logger.error("User %s not found", user_id)
        except DeployedApp.DoesNotExist:
            logger.error("DeployedApp %s not found", app_id)
        except Exception as e:
            logger.error(
                "Failed to update user credits for app %s: ", app_id, e, exc_info=True
            )
        return True
