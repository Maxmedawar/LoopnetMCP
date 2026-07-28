"""Authenticated customer-facing HTTP routes for the cloud platform."""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from cre_mcp.config import CreConfig
from cre_mcp.platform.authority import AuthorityOutcome, AuthorityResolver
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository

def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value

def _error(
    status: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=headers,
    )

class PlatformApi:
    """Request handlers bound to one platform database."""

    def __init__(self, config: CreConfig | None = None) -> None:
        self.configure(config or CreConfig())

    def configure(self, config: CreConfig) -> None:
        self.config = config
        self.authority = AuthorityResolver(
            config.cache_db_path,
            audience=config.oauth_audience,
            resource=config.oauth_resource,
            refresh_family_max_age=timedelta(
                days=config.oauth_refresh_family_max_age_days
            ),
        )
        self.repository = PlatformRepository(config.cache_db_path)
        self.entitlements = EntitlementStore(config.cache_db_path)

    def _bearer_challenge(
        self,
        *,
        error: str | None = None,
        description: str | None = None,
        scope: str | None = None,
    ) -> str:
        fields = ['realm="medawarcre"']
        if error is not None:
            fields.append(f'error="{error}"')
        if description is not None:
            fields.append(f'error_description="{description}"')
        if scope is not None:
            fields.append(f'scope="{scope}"')
        return "Bearer " + ", ".join(fields)

    def authorize(
        self,
        request: Request,
        *,
        scope: str | None = None,
        require_access: bool = True,
    ) -> tuple[AuthorityOutcome | None, JSONResponse | None]:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            return None, _error(
                401,
                "unauthorized",
                "Bearer token required",
                headers={"WWW-Authenticate": self._bearer_challenge()},
            )
        outcome = self.authority.resolve(token.strip())
        if outcome is None:
            return None, _error(
                401,
                "unauthorized",
                "Invalid, expired, revoked, or misdirected token",
                headers={
                    "WWW-Authenticate": self._bearer_challenge(
                        error="invalid_token",
                        description="The access token is not valid for this resource",
                    )
                },
            )
        if outcome.membership is None or outcome.workspace is None:
            return None, _error(
                403,
                "access_disabled",
                "The authenticated identity no longer has workspace membership",
            )
        if require_access and not outcome.access_allowed:
            return None, _error(
                403,
                "access_disabled",
                "Workspace access is not currently enabled",
            )
        if scope is not None and scope not in outcome.session.scopes:
            return None, _error(
                403,
                "forbidden",
                f"Missing required scope: {scope}",
                headers={
                    "WWW-Authenticate": self._bearer_challenge(
                        error="insufficient_scope",
                        description="The access token lacks the required scope",
                        scope=scope,
                    )
                },
            )
        return outcome, None

    async def parse_json(self, request: Request):
        try:
            value = await request.json()
        except Exception:
            return None, _error(400, "invalid_json", "Request body must be valid JSON")
        if not isinstance(value, dict):
            return None, _error(400, "invalid_body", "Request body must be a JSON object")
        return value, None

    async def me(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, require_access=False)
        if error is not None:
            return error
        return JSONResponse(_jsonable({
            "session": authority.session,
            "workspace": authority.workspace,
            "membership": authority.membership,
            "account": authority.account,
            "effective_access": authority.effective_access,
            "access_enabled": authority.access_allowed,
        }))

    async def entitlement_summary(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, require_access=False)
        if error is not None:
            return error
        return JSONResponse(_jsonable({
            "account": authority.account,
            "effective_access": authority.effective_access,
            "access_enabled": authority.access_allowed,
            "grants": self.entitlements.list_grants(authority.workspace.public_id),
        }))

    async def list_deals(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, scope="deals:read")
        if error is not None:
            return error
        stage = request.query_params.get("stage")
        try:
            deals = await self.repository.list_saved_deals(
                authority.workspace.public_id,
                stage=stage,
            )
        except ValueError as exc:
            return _error(422, "invalid_stage", str(exc))
        return JSONResponse({"deals": _jsonable(deals)})

    async def create_deal(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, scope="deals:write")
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        deal_ref = body.get("deal_ref")
        title = body.get("title")
        payload = body.get("payload", {})
        stage = body.get("stage", "watching")
        if not isinstance(deal_ref, str) or not isinstance(title, str):
            return _error(422, "invalid_deal", "deal_ref and title must be strings")
        if not isinstance(payload, dict):
            return _error(422, "invalid_payload", "payload must be a JSON object")
        if not isinstance(stage, str):
            return _error(422, "invalid_stage", "stage must be a string")
        try:
            deal = await self.repository.save_deal(
                authority.workspace.public_id,
                deal_ref,
                title,
                payload=payload,
                stage=stage,
            )
        except ValueError as exc:
            return _error(422, "invalid_deal", str(exc))
        if deal is None:
            return _error(404, "workspace_not_found", "Workspace does not exist")
        return JSONResponse({"deal": _jsonable(deal)}, status_code=201)
    async def get_deal(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, scope="deals:read")
        if error is not None:
            return error
        deal = await self.repository.get_saved_deal(
            authority.workspace.public_id,
            request.path_params["deal_id"],
        )
        if deal is None:
            return _error(404, "deal_not_found", "Deal does not exist")
        return JSONResponse({"deal": _jsonable(deal)})

    async def update_deal(self, request: Request) -> JSONResponse:
        authority, error = self.authorize(request, scope="deals:write")
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        fields: dict[str, Any] = {}
        if "title" in body:
            if not isinstance(body["title"], str):
                return _error(422, "invalid_title", "title must be a string")
            fields["title"] = body["title"]
        if "payload" in body:
            if not isinstance(body["payload"], dict):
                return _error(422, "invalid_payload", "payload must be a JSON object")
            fields["payload"] = body["payload"]
        if "stage" in body:
            if not isinstance(body["stage"], str):
                return _error(422, "invalid_stage", "stage must be a string")
            fields["stage"] = body["stage"]
        if not fields:
            return _error(422, "empty_update", "At least one updatable field is required")
        try:
            deal = await self.repository.update_saved_deal(
                authority.workspace.public_id,
                request.path_params["deal_id"],
                **fields,
            )
        except ValueError as exc:
            return _error(422, "invalid_deal", str(exc))
        if deal is None:
            return _error(404, "deal_not_found", "Deal does not exist")
        return JSONResponse({"deal": _jsonable(deal)})
    def routes(self) -> list[Route]:
        """Starlette routes for this API, ready to mount under any prefix."""
        return [
            Route(path, getattr(self, handler), methods=list(methods))
            for path, methods, handler in PLATFORM_ROUTE_SPECS
        ]


# (path, methods, handler-name) — the single source of truth for the platform
# HTTP surface, shared by ``PlatformApi.routes`` and the server's registration.
PLATFORM_ROUTE_SPECS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("/v1/me", ("GET",), "me"),
    ("/v1/entitlements", ("GET",), "entitlement_summary"),
    ("/v1/deals", ("GET",), "list_deals"),
    ("/v1/deals", ("POST",), "create_deal"),
    ("/v1/deals/{deal_id:int}", ("GET",), "get_deal"),
    ("/v1/deals/{deal_id:int}", ("PATCH",), "update_deal"),
)


def starlette_app(config: CreConfig | None = None) -> Starlette:
    """Build a standalone ASGI app for the customer-facing platform routes."""
    return Starlette(routes=PlatformApi(config).routes())


__all__ = ["PLATFORM_ROUTE_SPECS", "PlatformApi", "starlette_app"]
