from django.db import transaction

from app.models import AppSendingConfiguration, DeployedApp
from app.tasks import provision_credentials_for_app_task, set_app_provider_task


class ProviderNotFoundError(Exception):
    pass


class ProviderConfigNotFoundError(Exception):
    pass


class CredentialsAlreadyConfiguredError(Exception):
    pass


class ProviderService:
    @staticmethod
    async def provision_credentials(app: DeployedApp):
        try:
            config = await AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app, is_active=True)
        except AppSendingConfiguration.DoesNotExist:
            raise ProviderConfigNotFoundError

        if config.credentials:
            raise CredentialsAlreadyConfiguredError

        config.provisioning_status = (
            AppSendingConfiguration.ProvisioningStatusChoices.PENDING
        )
        config.provisioning_error = None
        await config.asave(update_fields=["provisioning_status", "provisioning_error"])
        provision_credentials_for_app_task.delay(
            app_id=app.id,
            owner_id=app.owner.id,
            provider_id=config.provider.id,
        )
        return config

    @staticmethod
    async def get_smtp_credentials(app: DeployedApp):
        try:
            config = await AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app, is_active=True)
        except AppSendingConfiguration.DoesNotExist:
            raise ProviderConfigNotFoundError()

        provider_type = config.provider.provider_type
        creds = config.credentials
        try:
            return {
                "host": creds["host"],
                "username": creds["username"],
                "password": creds["password"],
                "port": creds["port"],
                "provider": provider_type,
            }
        except KeyError:
            raise ValueError(
                f"Stored SMTP credentials for provider '{provider_type}' are incomplete."
            )

    # @staticmethod
    # def switch_app_provider(app_id: str, provider_id: int) -> bool:
    #     owner_id = DeployedApp.objects.get(id=app_id).owner_id
    #     set_app_provider_task.delay(app_id=app_id, user_id=owner_id, provider_id=provider_id)
    #
    #     # owner_id = DeployedApp.objects.aget(id=app_id).owner.id
    #     # with transaction.atomic():
    #     #     AppSendingConfiguration.objects.filter(app_id=app_id, is_active=True).update(
    #     #         is_active=False
    #     #     )
    #     #     AppSendingConfiguration.objects.update_or_create(
    #     #         app_id=app_id,
    #     #         provider_id=provider_id,
    #     #         defaults={"is_active": True, "user_id": owner_id, "credentials": {}},
    #     #     )
    #     #     return True
