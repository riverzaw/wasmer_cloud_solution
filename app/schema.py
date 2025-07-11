import enum
from datetime import date, datetime
from typing import Optional

import strawberry
import strawberry_django
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from graphql import GraphQLError
from strawberry import auto
from strawberry.relay import Node, NodeID
from strawberry.types import Info
from strawberry_django.optimizer import DjangoOptimizerExtension

from app.services.email_service import (EmailService, InsufficientCreditsError,
                                        NoActiveSendingConfigError)
from app.services.provider_service import (CredentialsAlreadyConfiguredError,
                                           ProviderConfigNotFoundError,
                                           ProviderNotFoundError,
                                           ProviderService)
from app.services.user_service import UserService

from . import models
from .models import AppSendingConfiguration, EmailUsage, Provider
from .tasks import set_app_provider_task


@strawberry_django.type(models.EmailUsage)
class EmailUsageType:
    app: auto
    date: auto
    sent_count: auto
    failed_count: auto
    read_count: auto


@strawberry.type
class EmailStatsType:
    total: int
    failed: int
    read: int
    sent: int


@strawberry.enum
class GroupByEnum(enum.Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@strawberry.type
class EmailUsageGroupType:
    timestamp: datetime
    emails: EmailStatsType


@strawberry.type
class UserEmailsType:
    user: "UserType"

    @strawberry.field
    async def sent_emails_count(self, info: Info) -> int:
        total_sent = await EmailUsage.objects.filter(user=self.user).aaggregate(
            total=Sum("sent_count")
        )
        return total_sent["total"] or 0

    @strawberry.field
    async def usage(
        self,
        info: Info,
        group_by: GroupByEnum,
        time_window: Optional[list[date]] = None,
    ) -> list[EmailUsageGroupType]:
        queryset = EmailUsage.objects.filter(user=self.user)
        if time_window and len(time_window) == 2:
            queryset = queryset.filter(date__range=time_window)

        if group_by == GroupByEnum.DAY:
            trunc_func = TruncDay
        elif group_by == GroupByEnum.WEEK:
            trunc_func = TruncWeek
        elif group_by == GroupByEnum.MONTH:
            trunc_func = TruncMonth
        else:
            raise ValidationError("Invalid groupBy, must be one of DAY, WEEK, MONTH.")

        usage_data = (
            queryset.annotate(period=trunc_func("date"))
            .values("period")
            .annotate(
                total=Sum("sent_count") + Sum("failed_count"),
                sent=Sum("sent_count"),
                failed=Sum("failed_count"),
                read=Sum("read_count"),
            )
            .order_by("period")
        )

        result = []
        async for row in usage_data:
            result.append(
                EmailUsageGroupType(
                    timestamp=row["period"],
                    emails=EmailStatsType(
                        total=row["total"],
                        failed=row["failed"],
                        sent=row["sent"],
                        read=row["read"],
                    ),
                )
            )
        return result


@strawberry_django.type(models.User)
class UserType(Node):
    id: NodeID[str]
    username: auto
    plan: auto
    credits: auto

    @classmethod
    async def resolve_nodes(
        cls, info: Info, node_ids: list[str], *args, **kwargs
    ) -> list["UserType"]:
        users = []
        for node_id in node_ids:
            try:
                user = await info.context["app_or_user"].load(node_id)
                users.append(user)
            except Exception:
                users.append(None)
        return users

    @strawberry.field
    async def deployed_apps(
        self, info: Info, active: Optional[bool] = None
    ) -> list["DeployedAppType"]:
        apps = await info.context["apps_by_owner"].load(self.id)
        if active is not None:
            apps = [app for app in apps if app.active == active]
        return apps

    @strawberry.field
    async def emails(self, info: Info) -> UserEmailsType:
        return UserEmailsType(user=self)


@strawberry.input
class DeployedAppsFilter:
    active: Optional[bool] = None


@strawberry_django.type(models.DeployedApp)
class DeployedAppType(Node):
    id: NodeID[str]
    active: auto
    owner: "UserType"

    @classmethod
    async def resolve_nodes(
        cls, info: Info, node_ids: list[str], *args, **kwargs
    ) -> list["DeployedAppType"]:
        apps = []
        for node_id in node_ids:
            try:
                app = await info.context["app_or_user"].load(node_id)
                apps.append(app)
            except Exception:
                apps.append(None)
        return apps

    @strawberry.field
    async def total_emails_count(self, info: Info) -> int:
        total_sent = await EmailUsage.objects.filter(app=self).aaggregate(
            total=Sum("sent_count") + Sum("failed_count")
        )
        return total_sent["total"] or 0

    @strawberry.field
    async def usage(
        self,
        info: Info,
        group_by: GroupByEnum,
        time_window: Optional[list[date]] = None,
    ) -> list[EmailUsageGroupType]:
        queryset = EmailUsage.objects.filter(app=self)
        if time_window and len(time_window) == 2:
            queryset = queryset.filter(date__range=time_window)

        if group_by == GroupByEnum.DAY:
            trunc_func = TruncDay
        elif group_by == GroupByEnum.WEEK:
            trunc_func = TruncWeek
        elif group_by == GroupByEnum.MONTH:
            trunc_func = TruncMonth
        else:
            raise ValidationError("Invalid groupBy, must be one of DAY, WEEK, MONTH.")

        usage_data = (
            queryset.annotate(period=trunc_func("date"))
            .values("period")
            .annotate(
                total=Sum("sent_count") + Sum("failed_count"),
                sent=Sum("sent_count"),
                failed=Sum("failed_count"),
                read=Sum("read_count"),
            )
            .order_by("period")
        )

        result = []
        async for row in usage_data:
            result.append(
                EmailUsageGroupType(
                    timestamp=row["period"],
                    emails=EmailStatsType(
                        total=row["total"],
                        failed=row["failed"],
                        sent=row["sent"],
                        read=row["read"],
                    ),
                )
            )
        return result


@strawberry.type
class SmtpCredentialsType:
    host: str
    port: int
    username: str
    password: str
    provider: str


@strawberry_django.type(models.Provider)
class ProviderType(Node):
    id: NodeID[str]
    name: auto
    provider_type: auto


@strawberry_django.type(models.AppSendingConfiguration)
class AppSendingConfigurationType(Node):
    app: "DeployedAppType"
    provisioning_status: auto
    provisioning_error: auto
    provider: "ProviderType"

    @strawberry.field
    async def provider_name(self) -> str:
        return self.provider.name


@strawberry.type
class Query:
    @strawberry.field
    async def node(self, info: Info, id: str) -> Optional[Node]:
        return await info.context["app_or_user"].load(id)

    @strawberry.field
    async def app_sending_configuration(
        self, info: Info, app_id: NodeID[str]
    ) -> Optional[AppSendingConfigurationType]:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not app_instance:
            return None
        try:
            config = await models.AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app_instance, is_active=True)
            return config
        except models.AppSendingConfiguration.DoesNotExist:
            return None


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def upgrade_account(self, info: Info, user_id: NodeID[str]) -> UserType:
        user_instance = await info.context["app_or_user"].load(user_id)
        if not user_instance:
            raise GraphQLError("User not found.")
        user = await UserService.upgrade_account(user_instance)
        return user

    @strawberry.mutation
    async def downgrade_account(self, info: Info, user_id: NodeID[str]) -> UserType:
        user_instance = await info.context["app_or_user"].load(user_id)
        if not user_instance:
            raise GraphQLError("User not found.")
        user = await UserService.downgrade_account(user_instance)
        return user

    @strawberry.mutation
    async def set_app_provider(
        self, info: Info, app_id: NodeID[str], provider_name: str
    ) -> bool:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not app_instance:
            raise GraphQLError("App not found.")
        try:
            provider_instance = await Provider.objects.aget(provider_type=provider_name)
        except Provider.DoesNotExist:
            raise GraphQLError("Provider not found.")
        try:
            set_app_provider_task.delay(
                app_instance.id, app_instance.owner_id, provider_instance.id
            )
            return True
        except ProviderNotFoundError:
            raise GraphQLError("Provider not found.")

    @strawberry.mutation
    async def provision_credentials(
        self, info: Info, app_id: NodeID[str]
    ) -> AppSendingConfigurationType:
        app_instance = await info.context["app_or_user"].load(app_id)
        try:
            config = await AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app_instance, is_active=True)
        except AppSendingConfiguration.DoesNotExist:
            raise GraphQLError("Provider configuration not found.")
        if not app_instance:
            raise GraphQLError("App not found.")
        try:
            await ProviderService.provision_credentials(app_instance)
        except ProviderConfigNotFoundError:
            raise GraphQLError("Provider configuration not found.")
        except CredentialsAlreadyConfiguredError:
            raise GraphQLError(
                "Credentials have been already configured for this app and provider."
            )
        return config

    @strawberry.mutation
    async def get_smtp_credentials(
        self, info: Info, app_id: NodeID[str]
    ) -> SmtpCredentialsType:
        """
        Retrieves the SMTP credentials for an app's active sending configuration.
        """
        app_instance = await info.context["app_or_user"].load(app_id)
        if not isinstance(app_instance, models.DeployedApp):
            raise GraphQLError("Invalid app ID provided.")

        try:
            config = await ProviderService.get_smtp_credentials(app_instance)
            return SmtpCredentialsType(
                host=config["host"],
                username=config["username"],
                password=config["password"],
                port=config["port"],
                provider=config["provider"],
            )
        except ProviderConfigNotFoundError:
            raise GraphQLError("No active sending configuration found.")
        except ValueError as e:
            raise GraphQLError(str(e))

    @strawberry.mutation
    async def send_email(
        self, info: Info, app_id: str, to: str, subject: str, html: str
    ) -> bool:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not isinstance(app_instance, models.DeployedApp):
            raise GraphQLError("Invalid app ID provided.")

        try:
            await EmailService.send_email(
                app_instance.id, app_instance.owner.id, to, subject, html
            )
        except InsufficientCreditsError:
            raise GraphQLError("Insufficient credits.")
        except NoActiveSendingConfigError:
            raise GraphQLError("No active sending configuration found for this app.")
        return True


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
