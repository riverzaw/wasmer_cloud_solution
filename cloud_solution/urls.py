from typing import Any, Optional, Union

from django.contrib import admin
from django.urls import path
from starlette.requests import Request
from starlette.responses import Response
from starlette.websockets import WebSocket
from strawberry.django.views import AsyncGraphQLView

from app.dataloaders import Loader
from app.schema import schema
from app.webhooks import mailersend_webhook, smtp2go_webhook


class AsyncGraphQLContext(AsyncGraphQLView):
    async def get_context(
        self, request: Union[Request, WebSocket], response: Optional[Response]
    ) -> Any:
        return {
            "apps_by_owner": Loader().apps_by_owner,
            "user": Loader().user,
            "app": Loader().app,
            "app_or_user": Loader().app_or_user,
        }


urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", AsyncGraphQLContext.as_view(schema=schema)),
    path("webhooks/mailersend", mailersend_webhook, name="mailersend_webhook"),
    path("webhooks/smtp2go", smtp2go_webhook, name="smtp2go_webhook"),
]
