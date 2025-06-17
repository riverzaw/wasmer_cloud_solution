from typing import Optional

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.relay import Node, NodeID
from strawberry.types import Info
from strawberry_django.optimizer import DjangoOptimizerExtension

from . import models


@strawberry_django.type(models.User)
class UserType(Node):
    id: NodeID[str]
    username: auto
    plan: auto

    @classmethod
    async def resolve_nodes(
        cls, info: Info, node_ids: list[str], *args, **kwargs
    ) -> list["UserType"]:
        users = []
        for node_id in node_ids:
            try:
                user = await info.context["user"].load(node_id)
                users.append(user)
            except Exception:
                users.append(None)
        return users

    @strawberry.field
    async def deployed_apps(
        self, info: Info, active: bool = None
    ) -> list["DeployedAppType"]:
        apps = await info.context["apps_by_owner"].load(self.id)
        if active is not None:
            apps = [app for app in apps if app.active == active]
        return apps


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
                app = await info.context["app"].load(node_id)
                apps.append(app)
            except Exception:
                apps.append(None)
        return apps


@strawberry.type
class Query:
    @strawberry.field
    async def node(self, info: Info, id: str) -> Optional[Node]:
        if id.startswith("u_"):
            return await info.context["user"].load(id)
        elif id.startswith("app_"):
            return await info.context["app"].load(id)
        return None


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def upgrade_account(self, info: Info, user_id: NodeID[str]) -> UserType:
        user_instance = await info.context["user"].load(user_id)
        if not user_instance:
            raise Exception("User not found.")
        if not isinstance(user_instance, models.User):
            raise Exception("Invalid user ID provided.")
        user_instance.plan = models.User.Plan.PRO
        await user_instance.asave()
        return UserType(
            id=user_instance.id,
            username=user_instance.username,
            plan=user_instance.plan,
        )

    @strawberry.mutation
    async def downgrade_account(self, info: Info, user_id: NodeID[str]) -> UserType:
        user_instance = await info.context["user"].load(user_id)
        if not user_instance:
            raise Exception("User not found.")
        if not isinstance(user_instance, models.User):
            raise Exception("Invalid user ID provided.")
        user_instance.plan = models.User.Plan.HOBBY
        await user_instance.asave()
        return UserType(
            id=user_instance.id,
            username=user_instance.username,
            plan=user_instance.plan,
        )


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
