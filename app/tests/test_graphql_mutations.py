import pytest

from ..models import User
from .utils import app_factory, gql_client, provider_factory, user_factory

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestUserMutations:
    @pytest.mark.parametrize(
        "initial_plan,mutation_name,expected_plan",
        [
            (User.Plan.HOBBY, "upgradeAccount", User.Plan.PRO),
            (User.Plan.PRO, "downgradeAccount", User.Plan.HOBBY),
        ],
    )
    async def test_account_plan_changes(
        self, gql_client, user_factory, initial_plan, mutation_name, expected_plan
    ):
        user = await user_factory(plan=initial_plan)

        mutation = f"""
            mutation($userId: String!) {{
                {mutation_name}(userId: $userId) {{
                    plan
                }}
            }}
        """

        response = await gql_client.query(mutation, {"userId": user.id})
        assert response["data"][mutation_name]["plan"] == expected_plan

    async def test_upgrade_invalid_user(self, gql_client):
        mutation = """
            mutation {
                upgradeAccount(userId: "u_nonexistent") {
                    plan
                }
            }
        """
        response = await gql_client.query(mutation)
        assert "errors" in response
        assert response["data"] is None
        assert response["errors"][0]["message"] == "User not found."

    async def test_downgrade_invalid_user(self, gql_client):
        mutation = """
            mutation {
                downgradeAccount(userId: "u_nonexistent") {
                    plan
                }
            }
        """
        response = await gql_client.query(mutation)
        assert "errors" in response
        assert response["data"] is None
        assert response["errors"][0]["message"] == "User not found."


class TestAppProviderMutations:
    async def test_set_app_provider_success(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        provider = await provider_factory(provider_type="MAILERSEND", name="MailerSend")
        mutation = """
            mutation($appId: String!, $providerName: String!) {
                setAppProvider(appId: $appId, providerName: $providerName)
            }
        """
        variables = {"appId": app.id, "providerName": provider.provider_type}
        response = await gql_client.query(mutation, variables)
        assert response["data"]["setAppProvider"] is True

    async def test_set_app_provider_invalid_provider(
        self, gql_client, user_factory, app_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        mutation = """
            mutation($appId: String!, $providerName: String!) {
                setAppProvider(appId: $appId, providerName: $providerName)
            }
        """
        variables = {"appId": app.id, "providerName": "NONEXISTENT"}
        response = await gql_client.query(mutation, variables)
        assert "errors" in response
        assert "Provider not found." in response["errors"][0]["message"]


class TestProvisionCredentialsMutation:
    async def test_provision_credentials_success(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        provider = await provider_factory()
        from app.models import AppSendingConfiguration

        config = await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials={},
            provisioning_status=AppSendingConfiguration.ProvisioningStatusChoices.PENDING,
        )
        mutation = """
            mutation($appId: String!) {
                provisionCredentials(appId: $appId) {
                    providerName
                    provisioningStatus
                    provisioningError
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert response["data"]["provisionCredentials"]["providerName"] == provider.name
        assert (
            response["data"]["provisionCredentials"]["provisioningStatus"]
            == config.provisioning_status
        )
        assert response["data"]["provisionCredentials"]["provisioningError"] is None

    async def test_provision_credentials_already_configured(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        provider = await provider_factory()
        from app.models import AppSendingConfiguration

        config = await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials={"host": "smtp.example.com"},
            provisioning_status="idle",
        )
        mutation = """
            mutation($appId: String!) {
                provisionCredentials(appId: $appId) {
                    providerName
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert "errors" in response
        assert (
            "Credentials have been already configured"
            in response["errors"][0]["message"]
        )

    async def test_provision_credentials_no_config(self, gql_client, app_factory):
        app = await app_factory()
        mutation = """
            mutation($appId: String!) {
                provisionCredentials(appId: $appId) {
                    providerName
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert "errors" in response
        assert "Provider configuration not found." in response["errors"][0]["message"]


class TestGetSmtpCredentialsMutation:
    async def test_get_smtp_credentials_success(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        provider = await provider_factory(
            provider_type="GENERIC_SMTP", name="SMTP Test"
        )
        from app.models import AppSendingConfiguration

        creds = {
            "host": "smtp.example.com",
            "port": 587,
            "username": "user",
            "password": "pass",
        }
        await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials=creds,
            provisioning_status="success",
        )
        mutation = """
            mutation($appId: String!) {
                getSmtpCredentials(appId: $appId) {
                    host
                    port
                    username
                    password
                    provider
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert response["data"]["getSmtpCredentials"]["host"] == creds["host"]
        assert (
            response["data"]["getSmtpCredentials"]["provider"] == provider.provider_type
        )

    async def test_get_smtp_credentials_no_config(self, gql_client, app_factory):
        app = await app_factory()
        mutation = """
            mutation($appId: String!) {
                getSmtpCredentials(appId: $appId) {
                    host
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert "errors" in response
        assert (
            "No active sending configuration found" in response["errors"][0]["message"]
        )

    async def test_get_smtp_credentials_incomplete(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory()
        app = await app_factory(owner=user)
        provider = await provider_factory()
        from app.models import AppSendingConfiguration

        creds = {"host": "smtp.example.com"}  # missing required fields
        await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials=creds,
            provisioning_status="success",
        )
        mutation = """
            mutation($appId: String!) {
                getSmtpCredentials(appId: $appId) {
                    host
                }
            }
        """
        response = await gql_client.query(mutation, {"appId": app.id})
        assert "errors" in response
        assert "incomplete" in response["errors"][0]["message"].lower()


class TestSendEmailMutation:
    async def test_send_email_success(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory(plan="PRO", credits=10)
        app = await app_factory(owner=user)
        provider = await provider_factory()
        from app.models import AppSendingConfiguration

        await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials={
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
            },
            provisioning_status="success",
        )
        mutation = """
            mutation($appId: String!, $to: String!, $subject: String!, $html: String!) {
                sendEmail(appId: $appId, to: $to, subject: $subject, html: $html)
            }
        """
        variables = {
            "appId": app.id,
            "to": "test@example.com",
            "subject": "Test",
            "html": "<b>Hi</b>",
        }
        response = await gql_client.query(mutation, variables)
        assert response["data"]["sendEmail"] is True

    async def test_send_email_insufficient_credits(
        self, gql_client, user_factory, app_factory, provider_factory
    ):
        user = await user_factory(plan="HOBBY", credits=0)
        app = await app_factory(owner=user)
        provider = await provider_factory()
        from app.models import AppSendingConfiguration

        await AppSendingConfiguration.objects.acreate(
            app=app,
            user=user,
            provider=provider,
            is_active=True,
            credentials={
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pass",
            },
            provisioning_status="success",
        )
        mutation = """
            mutation($appId: String!, $to: String!, $subject: String!, $html: String!) {
                sendEmail(appId: $appId, to: $to, subject: $subject, html: $html)
            }
        """
        variables = {
            "appId": app.id,
            "to": "test@example.com",
            "subject": "Test",
            "html": "<b>Hi</b>",
        }
        response = await gql_client.query(mutation, variables)
        assert "errors" in response
        assert "Insufficient credits" in response["errors"][0]["message"]

    async def test_send_email_no_config(self, gql_client, user_factory, app_factory):
        user = await user_factory()
        app = await app_factory(owner=user)
        mutation = """
            mutation($appId: String!, $to: String!, $subject: String!, $html: String!) {
                sendEmail(appId: $appId, to: $to, subject: $subject, html: $html)
            }
        """
        variables = {
            "appId": app.id,
            "to": "test@example.com",
            "subject": "Test",
            "html": "<b>Hi</b>",
        }
        response = await gql_client.query(mutation, variables)
        assert "errors" in response
        assert (
            "No active sending configuration found" in response["errors"][0]["message"]
        )

    async def test_send_email_invalid_app(self, gql_client):
        mutation = """
            mutation($appId: String!, $to: String!, $subject: String!, $html: String!) {
                sendEmail(appId: $appId, to: $to, subject: $subject, html: $html)
            }
        """
        variables = {
            "appId": "app_nonexistent",
            "to": "test@example.com",
            "subject": "Test",
            "html": "<b>Hi</b>",
        }
        response = await gql_client.query(mutation, variables)
        assert "errors" in response
        assert "Invalid app ID provided." in response["errors"][0]["message"]
