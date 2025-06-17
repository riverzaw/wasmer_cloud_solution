import base64
import json
from typing import Optional

import faker
import pytest
from django.test import AsyncClient

from app.models import DeployedApp, User

fake = faker.Faker()


class GraphQLTestClient:
    def __init__(self, client: AsyncClient):
        self.client = client
        self.endpoint = "/graphql/"

    async def query(self, query: str, variables: Optional[dict] = None) -> dict:
        response = await self.client.post(
            self.endpoint,
            data=json.dumps({"query": query, "variables": variables}),
            content_type="application/json",
        )
        return json.loads(response.content)

    def encode_id(self, type_name: str, id_value: str) -> str:
        return base64.b64encode(f"{type_name}:{id_value}".encode("utf-8")).decode(
            "utf-8"
        )


@pytest.fixture
async def gql_client():
    return GraphQLTestClient(AsyncClient())


@pytest.fixture
async def user_factory():
    async def create_user(**kwargs):
        user_id = kwargs.pop("id", f"u_{fake.uuid4()}")
        username = kwargs.pop("username", fake.user_name())
        plan = kwargs.pop("plan", User.Plan.HOBBY)

        return await User.objects.acreate(
            id=user_id, username=username, plan=plan, **kwargs
        )

    return create_user


@pytest.fixture
async def app_factory(user_factory):
    async def create_app(**kwargs):
        app_id = kwargs.pop("id", f"app_{fake.uuid4()}")
        if "owner" not in kwargs:
            kwargs["owner"] = await user_factory()
        owner = kwargs.pop("owner", None)
        active = kwargs.pop("active", True)

        return await DeployedApp.objects.acreate(
            id=app_id, owner=owner, active=active, **kwargs
        )

    return create_app
