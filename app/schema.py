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

from . import models
from .models import EmailUsage
from .tasks import (provision_credentials_for_app,
                    send_email_with_credit_check, set_app_provider)


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
        if id.startswith("u_"):
            return await info.context["app_or_user"].load(id)
        elif id.startswith("app_"):
            return await info.context["app_or_user"].load(id)
        return None

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
        if not isinstance(user_instance, models.User):
            raise GraphQLError("Invalid user ID provided.")
        user_instance.plan = models.User.Plan.PRO
        await user_instance.asave()
        return user_instance

    @strawberry.mutation
    async def downgrade_account(self, info: Info, user_id: NodeID[str]) -> UserType:
        user_instance = await info.context["app_or_user"].load(user_id)
        if not user_instance:
            raise GraphQLError("User not found.")
        if not isinstance(user_instance, models.User):
            raise GraphQLError("Invalid user ID provided.")
        user_instance.plan = models.User.Plan.HOBBY
        user_instance.credits = models.User.EMAIL_HOBBY_CREDITS
        await user_instance.asave()
        return user_instance

    @strawberry.mutation
    async def set_app_provider(
        self, info: Info, app_id: NodeID[str], provider_name: str
    ) -> bool:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not app_instance:
            raise GraphQLError("App not found.")

        try:
            provider_instance = await models.Provider.objects.aget(
                provider_type=provider_name
            )
        except models.Provider.DoesNotExist:
            raise GraphQLError(
                "Provider not found."
            )

        set_app_provider.delay(
            app_id=app_instance.id,
            user_id=app_instance.owner.id,
            provider_id=provider_instance.id,
        )

        return True

    @strawberry.mutation
    async def provision_credentials(
        self, info: Info, app_id: NodeID[str]
    ) -> AppSendingConfigurationType:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not app_instance:
            raise GraphQLError("App not found.")
        try:
            config = await models.AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app_instance, is_active=True)
        except models.AppSendingConfiguration.DoesNotExist:
            raise GraphQLError("Provider configuration not found.")

        if config.credentials:
            raise GraphQLError(
                "Credentials have been already configured for this configuration."
            )

        config.provisioning_status = (
            models.AppSendingConfiguration.ProvisioningStatusChoices.PENDING
        )
        provision_credentials_for_app.delay(
            app_id=app_instance.id, provider_id=config.provider.id
        )
        return config

    @strawberry.mutation
    async def get_smtp_credentials(
        self, info: Info, app_id: NodeID[str]
    ) -> SmtpCredentialsType:
        """
        Retrieves the SMTP credentials for an app's active sending configuration.
        This will fail if the active provider does not support SMTP.
        """
        app_instance = await info.context["app_or_user"].load(app_id)
        if not isinstance(app_instance, models.DeployedApp):
            raise GraphQLError("Invalid app ID provided.")

        try:
            config = await models.AppSendingConfiguration.objects.select_related(
                "provider"
            ).aget(app=app_instance, is_active=True)
        except models.AppSendingConfiguration.DoesNotExist:
            raise GraphQLError("No active sending configuration found for this app.")

        provider_type = config.provider.provider_type
        creds = config.credentials
        try:
            return SmtpCredentialsType(
                host=creds["host"],
                username=creds["username"],
                password=creds["password"],
                port=creds["port"],
                provider=provider_type,
            )
        except KeyError:
            raise GraphQLError(
                f"Stored SMTP credentials for provider '{provider_type}' are incomplete. "
                "Please configure the SMTP credentials properly."
            )

    @strawberry.mutation
    async def send_email(
        self, info: Info, app_id: str, to: str, subject: str, html: str
    ) -> bool:
        app_instance = await info.context["app_or_user"].load(app_id)
        if not isinstance(app_instance, models.DeployedApp):
            raise GraphQLError("Invalid app ID provided.")

        owner = app_instance.owner
        if owner.plan == models.User.Plan.HOBBY and owner.credits <= 0:
            usage, _ = await EmailUsage.objects.aget_or_create(
                app=app_instance,
                user=owner,
                date=date.today(),
            )
            usage.failed_count += 1
            await usage.asave()
            raise GraphQLError("Insufficient credits.")

        try:
            await models.AppSendingConfiguration.objects.aget(
                app=app_instance, is_active=True
            )
        except models.AppSendingConfiguration.DoesNotExist:
            raise GraphQLError("No active sending configuration found for this app.")

        send_email_with_credit_check.delay(
            app_id=app_id, to=to, subject=subject, html=html, user_id=owner.id
        )

        return True


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
