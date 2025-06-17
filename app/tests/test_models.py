import pytest
from django.db import IntegrityError

from app.models import DeployedApp, User

from .utils import app_factory, user_factory

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestUser:
    async def test_user_creation_valid(self, user_factory):
        user = await user_factory()
        assert user.id.startswith("u_")
        assert user.plan == User.Plan.HOBBY

    async def test_user_invalid_id(self, user_factory):
        with pytest.raises(ValueError, match="User ID must start with 'u_'"):
            await user_factory(id="invalid_id")

    async def test_user_plan_upgrade(self, user_factory):
        user = await user_factory()
        user.plan = User.Plan.PRO
        await user.asave()
        assert user.plan == User.Plan.PRO

    @pytest.mark.parametrize("username", [None])
    async def test_user_invalid_username(self, user_factory, username):
        with pytest.raises(IntegrityError):
            await user_factory(username=username)


class TestDeployedApp:
    async def test_app_creation_valid(self, app_factory):
        app = await app_factory()
        assert app.id.startswith("app_")
        assert app.active is True

    async def test_app_invalid_id(self, app_factory):
        with pytest.raises(ValueError, match="App ID must start with 'app_'"):
            await app_factory(id="invalid_id")

    async def test_app_cascade_delete(self, user_factory, app_factory):
        user = await user_factory()
        app = await app_factory(owner=user)
        await user.adelete()
        with pytest.raises(DeployedApp.DoesNotExist):
            await DeployedApp.objects.aget(id=app.id)
