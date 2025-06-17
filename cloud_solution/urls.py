from typing import Any, Optional, Union

from django.contrib import admin
from django.urls import path
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket
from strawberry.django.views import AsyncGraphQLView

from app.dataloaders import Loader
from app.schema import schema


class AsyncGraphQLContext(AsyncGraphQLView):
    async def get_context(
        self, request: Union[Request, WebSocket], response: Optional[Response]
    ) -> Any:
        return {
            "apps_by_owner": Loader().apps_by_owner,
            "user": Loader().user,
            "app": Loader().app,
        }


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", AsyncGraphQLContext.as_view(schema=schema)),
]
