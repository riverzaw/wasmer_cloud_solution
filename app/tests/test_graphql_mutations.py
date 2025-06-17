import pytest

from ..models import User
from .utils import gql_client, user_factory

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
