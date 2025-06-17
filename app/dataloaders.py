from collections import defaultdict
from typing import Optional

from strawberry.dataloader import DataLoader

from app.models import DeployedApp, User


async def load_apps_for_users(keys: list[str]) -> list[list[DeployedApp]]:
    deployed_apps = [
        app
        async for app in DeployedApp.objects.filter(owner_id__in=keys).select_related(
            "owner"
        )
    ]
    apps_by_owner_id = defaultdict(list)
    for app in deployed_apps:
        apps_by_owner_id[app.owner_id].append(app)
    return [apps_by_owner_id.get(user_id, []) for user_id in keys]


async def load_single_user(keys: list[str]) -> list[Optional[User]]:
    users = [user async for user in User.objects.filter(id__in=keys)]
    user_map = {str(user.id): user for user in users}
    return [user_map.get(key) for key in keys]


async def load_single_app(keys: list[str]) -> list[Optional[DeployedApp]]:
    apps = [
        app
        async for app in DeployedApp.objects.filter(id__in=keys).select_related("owner")
    ]
    app_map = {str(app.id): app for app in apps}
    return [app_map.get(key) for key in keys]


class Loader:
    def __init__(self):
        self.apps_by_owner = DataLoader(load_fn=load_apps_for_users)
        self.user = DataLoader(load_fn=load_single_user)
        self.app = DataLoader(load_fn=load_single_app)
