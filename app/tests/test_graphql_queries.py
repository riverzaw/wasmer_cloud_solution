import pytest

from .utils import app_factory, gql_client, provider_factory, user_factory

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestUserQueries:
    async def test_user_query_with_apps(self, gql_client, user_factory, app_factory):
        user = await user_factory()
        apps = [
            await app_factory(owner=user),
            await app_factory(owner=user, active=False),
        ]

        query = """
            query($id: String!) {
                node(id: $id) {
                    ... on UserType {
                        id
                        username
                        plan
                        deployedApps {
                            id
                            active
                            owner { id }
                        }
                    }
                }
            }
        """

        response = await gql_client.query(query, {"id": user.id})
        assert response["data"]["node"] is not None
        assert response["data"]["node"]["id"] == gql_client.encode_id(
            "UserType", user.id
        )
        assert response["data"]["node"]["username"] == user.username
        assert len(response["data"]["node"]["deployedApps"]) == 2

    async def test_get_user_by_node(self, gql_client, user_factory, app_factory):
        user = await user_factory()
        active_app = await app_factory(owner=user, active=True)
        inactive_app = await app_factory(owner=user, active=False)

        query = """
        query($id: String!) {
            node(id: $id) {
                ... on UserType {
                    id
                    username
                    plan
                    deployedApps {
                        id
                        active
                    }
                }
            }
        }
        """
        response = await gql_client.query(query, {"id": user.id})
        assert response["data"]["node"] is not None
        assert response["data"]["node"]["id"] == gql_client.encode_id(
            "UserType", user.id
        )
        assert response["data"]["node"]["username"] == user.username
        assert response["data"]["node"]["plan"] == user.plan
        assert response["data"]["node"]["deployedApps"] == [
            {
                "id": gql_client.encode_id("DeployedAppType", active_app.id),
                "active": True,
            },
            {
                "id": gql_client.encode_id("DeployedAppType", inactive_app.id),
                "active": False,
            },
        ]

    async def test_get_user_active_apps(self, gql_client, user_factory, app_factory):
        user = await user_factory()
        active_app = await app_factory(owner=user, active=True)
        inactive_app = await app_factory(owner=user, active=False)

        query = """
        query($id: String!) {
            node(id: $id) {
                ... on UserType {
                    id
                    username
                    plan
                    deployedApps(active: true) {
                        id
                        active
                    }
                }
            }
        }
        """
        response = await gql_client.query(query, {"id": user.id})
        assert response["data"]["node"] is not None
        assert response["data"]["node"]["id"] == gql_client.encode_id(
            "UserType", user.id
        )
        assert response["data"]["node"]["username"] == user.username
        assert response["data"]["node"]["plan"] == user.plan
        assert response["data"]["node"]["deployedApps"] == [
            {
                "id": gql_client.encode_id("DeployedAppType", active_app.id),
                "active": True,
            }
        ]
        assert {
            "id": gql_client.encode_id("DeployedAppType", inactive_app.id),
            "active": False,
        } not in response["data"]["node"]["deployedApps"]

    async def test_get_app_by_node(self, gql_client, user_factory, app_factory):
        app = await app_factory()

        query = """
        query($id: String!) {
            node(id: $id) {
                ... on DeployedAppType {
                    id
                    active
                    owner {
                        id
                        username
                    }
                }
            }
        }
        """
        response = await gql_client.query(query, {"id": app.id})
        assert response["data"]["node"] is not None
        assert response["data"]["node"]["id"] == gql_client.encode_id(
            "DeployedAppType", app.id
        )
        assert response["data"]["node"]["active"] == app.active

    async def test_get_nonexistent_node(self, gql_client):
        query = """
        query {
            node(id: "u_nonexistent") {
                __typename
            }
        }
        """
        response = await gql_client.query(query)
        assert response["data"]["node"] is None


class TestAppSendingConfigurationQuery:
    async def test_app_sending_configuration_success(
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
            provisioning_status="pending",
            provisioning_error=None,
        )
        query = """
            query($appId: String!) {
                appSendingConfiguration(appId: $appId) {
                    providerName
                    provisioningStatus
                    provisioningError
                    app { id }
                }
            }
        """
        response = await gql_client.query(query, {"appId": app.id})
        assert (
            response["data"]["appSendingConfiguration"]["providerName"] == provider.name
        )
        assert (
            response["data"]["appSendingConfiguration"]["provisioningStatus"]
            == config.provisioning_status
        )
        assert response["data"]["appSendingConfiguration"]["provisioningError"] is None
        assert response["data"]["appSendingConfiguration"]["app"][
            "id"
        ] == gql_client.encode_id("DeployedAppType", app.id)

    async def test_app_sending_configuration_not_found(self, gql_client, app_factory):
        app = await app_factory()
        query = """
            query($appId: String!) {
                appSendingConfiguration(appId: $appId) {
                    providerName
                    provisioningStatus
                    provisioningError
                }
            }
        """
        response = await gql_client.query(query, {"appId": app.id})
        assert response["data"]["appSendingConfiguration"] is None
