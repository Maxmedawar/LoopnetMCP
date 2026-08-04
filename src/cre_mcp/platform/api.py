"""Authenticated customer-facing HTTP routes for the cloud platform."""
from __future__ import annotations
import asyncio
import hmac
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.platform.admin import (
    ADMIN_SCOPE,
    AdminAuditError,
    AdminConflictError,
    AdminControlStore,
    AdminForbiddenError,
    AdminNotFoundError,
    AdminValidationError,
)
from cre_mcp.platform.authority import AuthorityOutcome, AuthorityResolver
from cre_mcp.platform.auth import OAuthSessionStore
from cre_mcp.platform.connection import (
    BrowserSessionStore,
    ClerkHumanIdentityVerifier,
    HumanIdentityStore,
    HumanIdentityVerifier,
    PendingAuthorization,
    PendingAuthorizationStore,
)
from cre_mcp.platform.entitlements import EntitlementStore
from cre_mcp.platform.repository import PlatformRepository
from cre_mcp.platform.providers.core import (
    ProviderSyncService,
    ProviderValidationError,
    ReconciliationConflictError,
    ReconciliationNotFoundError,
    ReconciliationValidationError,
    WebhookSignatureError,
    WebhookTimestampError,
    decode_json_object,
    salvage_leading_identity,
    verify_hmac_signature,
)
from cre_mcp.platform.providers.reconciliation import (
    ProviderReconciliationStore,
)
from cre_mcp.platform.providers.skool import SKOOL_EVENT_TYPES, parse_skool_event
from cre_mcp.platform.providers.stripe import (
    STRIPE_EVENT_TYPES,
    parse_stripe_event,
)

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


def _oauth_error(status: int, code: str, description: str) -> JSONResponse:
    return JSONResponse(
        {"error": code, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


OAUTH_PUBLIC_SCOPES = frozenset({"mcp:tools", "deals:read", "deals:write"})
AUTHORITY_SELECTORS = frozenset(
    {"workspace", "workspace_id", "user", "user_id", "profile", "plan", "territory"}
)
BLOCKED_ACCOUNT_STATES = frozenset(
    {"suspended", "under_review", "canceled", "deletion_pending", "deleted"}
)

class PlatformApi:
    """Request handlers bound to one platform database."""

    def __init__(
        self,
        config: CreConfig | None = None,
        *,
        human_identity_verifier: HumanIdentityVerifier | None = None,
    ) -> None:
        self._injected_human_identity_verifier = human_identity_verifier
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
        self.repository = PlatformRepository(config=config)
        self.entitlements = EntitlementStore(config.cache_db_path)
        self.admin = AdminControlStore(config.cache_db_path)
        self.provider_sync = ProviderSyncService(config)
        self.provider_reconciliation = ProviderReconciliationStore(
            config.cache_db_path,
            self.provider_sync,
        )
        self.oauth = OAuthSessionStore(
            config.cache_db_path,
            refresh_family_max_age=timedelta(
                days=config.oauth_refresh_family_max_age_days
            ),
        )
        self.human_identities = HumanIdentityStore(config.cache_db_path)
        self.browser_sessions = BrowserSessionStore(
            config.cache_db_path,
            ttl=timedelta(seconds=config.browser_session_ttl_seconds),
        )
        self.pending_authorizations = PendingAuthorizationStore(
            config.cache_db_path
        )
        self.human_identity_verifier = self._injected_human_identity_verifier
        if (
            self.human_identity_verifier is None
            and config.human_identity_provider == "clerk"
            and config.clerk_secret_key is not None
            and config.clerk_authorized_parties
        ):
            self.human_identity_verifier = ClerkHumanIdentityVerifier(config)

    @staticmethod
    def _connection_state(db_path, user_id: int) -> tuple[dict[str, Any] | None, list[str]]:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            user = connection.execute(
                "SELECT id,email,name FROM platform_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if user is None:
                return None, []
            rows = connection.execute(
                """
                SELECT workspace.public_id
                FROM platform_memberships AS membership
                JOIN platform_workspaces AS workspace
                  ON workspace.id=membership.workspace_id
                WHERE membership.user_id=?
                ORDER BY workspace.id
                """,
                (user_id,),
            ).fetchall()
        return dict(user), [str(row["public_id"]) for row in rows]

    async def _state_for_user(self, user_id: int) -> tuple[dict[str, Any] | None, list[str]]:
        return await asyncio.to_thread(
            self._connection_state, self.config.cache_db_path, user_id
        )

    async def _account_is_blocked(self, workspace: str) -> bool:
        account = await asyncio.to_thread(self.entitlements.get_account, workspace)
        return account is not None and account.state in BLOCKED_ACCOUNT_STATES

    def _browser_session(self, request: Request):
        token = request.cookies.get(self.config.browser_cookie_name)
        if not token:
            return None
        return self.browser_sessions.validate(token)

    def _connection_redirect(self, pending_handle: str) -> RedirectResponse:
        parsed = urlsplit(self.config.connection_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["request"] = [pending_handle]
        location = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )
        return RedirectResponse(location, status_code=303)

    def _connection_origin(self) -> str:
        parsed = urlsplit(self.config.connection_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _with_connection_cors(self, request: Request, response: Response) -> Response:
        origin = request.headers.get("origin")
        if origin and hmac.compare_digest(origin, self._connection_origin()):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response

    async def browser_session_options(self, request: Request) -> Response:
        origin = request.headers.get("origin", "")
        if not origin or not hmac.compare_digest(origin, self._connection_origin()):
            return _error(403, "origin_forbidden", "Connection origin is not allowed")
        requested_method = request.headers.get("access-control-request-method", "")
        if requested_method.upper() != "POST":
            return _error(403, "method_forbidden", "Connection method is not allowed")
        requested_headers = {
            item.strip().casefold()
            for item in request.headers.get("access-control-request-headers", "").split(",")
            if item.strip()
        }
        if not requested_headers.issubset({"authorization", "content-type"}):
            return _error(403, "headers_forbidden", "Connection headers are not allowed")
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )

    async def oauth_metadata(self, request: Request) -> JSONResponse:
        issuer = self.config.oauth_issuer.rstrip("/")
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/oauth/authorize",
                "token_endpoint": issuer + "/oauth/token",
                "registration_endpoint": issuer + "/oauth/register",
                "revocation_endpoint": issuer + "/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": sorted(OAUTH_PUBLIC_SCOPES),
            },
            headers={"Cache-Control": "public, max-age=300"},
        )

    async def protected_resource_metadata(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "resource": self.config.oauth_resource,
                "authorization_servers": [self.config.oauth_issuer.rstrip("/")],
                "bearer_methods_supported": ["header"],
                "scopes_supported": sorted(OAUTH_PUBLIC_SCOPES),
            },
            headers={"Cache-Control": "public, max-age=300"},
        )

    async def oauth_register(self, request: Request) -> JSONResponse:
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        if AUTHORITY_SELECTORS.intersection(body):
            return _error(
                422,
                "authority_selector_forbidden",
                "OAuth clients cannot select server-owned authority",
            )
        allowed = {
            "client_name",
            "redirect_uris",
            "scope",
            "token_endpoint_auth_method",
            "grant_types",
            "response_types",
        }
        if set(body).difference(allowed):
            return _oauth_error(400, "invalid_client_metadata", "unsupported client metadata")
        redirects = body.get("redirect_uris")
        name = body.get("client_name", "MCP client")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 128
            or not isinstance(redirects, list)
            or not redirects
            or len(redirects) > 8
            or any(not isinstance(uri, str) for uri in redirects)
        ):
            return _oauth_error(400, "invalid_client_metadata", "client name and redirect URIs are required")
        if body.get("token_endpoint_auth_method", "none") != "none":
            return _oauth_error(400, "invalid_client_metadata", "only public PKCE clients are supported")
        if body.get("grant_types", ["authorization_code", "refresh_token"]) not in (
            ["authorization_code"],
            ["authorization_code", "refresh_token"],
        ):
            return _oauth_error(400, "invalid_client_metadata", "unsupported grant types")
        if body.get("response_types", ["code"]) != ["code"]:
            return _oauth_error(400, "invalid_client_metadata", "only the code response type is supported")
        raw_scope = body.get("scope", "mcp:tools")
        if not isinstance(raw_scope, str):
            return _oauth_error(400, "invalid_client_metadata", "scope must be a string")
        scopes = tuple(dict.fromkeys(raw_scope.split()))
        if not scopes or not set(scopes).issubset(OAUTH_PUBLIC_SCOPES):
            return _oauth_error(400, "invalid_scope", "requested scope is not supported")
        try:
            client = await asyncio.to_thread(
                self.oauth.register_client,
                name,
                tuple(redirects),
                scopes,
            )
        except ValueError as exc:
            return _oauth_error(400, "invalid_redirect_uri", str(exc))
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_name": client.name,
                "redirect_uris": list(client.redirect_uris),
                "scope": " ".join(client.scopes),
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    async def oauth_authorize(self, request: Request):
        pairs = request.query_params.multi_items()
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            return _error(400, "duplicate_parameter", "OAuth parameters cannot repeat")
        supplied = set(keys)
        if AUTHORITY_SELECTORS.intersection(supplied):
            return _error(
                422,
                "authority_selector_forbidden",
                "Workspace, identity, profile, plan, and territory are server-owned",
            )
        allowed = {
            "request",
            "response_type",
            "client_id",
            "redirect_uri",
            "scope",
            "state",
            "code_challenge",
            "code_challenge_method",
            "resource",
        }
        if supplied.difference(allowed):
            return _error(400, "invalid_request", "Unsupported authorization parameter")

        pending_handle = request.query_params.get("request")
        if pending_handle:
            if len(supplied) != 1:
                return _error(400, "invalid_request", "Pending request cannot be combined with OAuth inputs")
            pending = self.pending_authorizations.get(pending_handle)
            if pending is None:
                return _error(400, "invalid_request", "Authorization request is invalid or expired")
        else:
            required = {
                "response_type",
                "client_id",
                "redirect_uri",
                "state",
                "code_challenge",
                "code_challenge_method",
            }
            if not required.issubset(supplied):
                return _error(400, "invalid_request", "Required authorization parameter is missing")
            if request.query_params["response_type"] != "code":
                return _error(400, "unsupported_response_type", "Only code is supported")
            client_id = request.query_params["client_id"]
            client = self.oauth.get_client(client_id)
            redirect_uri = request.query_params["redirect_uri"]
            if client is None or not client.active or redirect_uri not in client.redirect_uris:
                return _error(400, "invalid_request", "OAuth client or redirect URI is invalid")
            scopes = tuple(dict.fromkeys(request.query_params.get("scope", "mcp:tools").split()))
            if not scopes or not set(scopes).issubset(set(client.scopes)):
                return _error(400, "invalid_scope", "Requested scope is not registered")
            resource = request.query_params.get("resource", self.config.oauth_resource)
            if resource != self.config.oauth_resource:
                return _error(400, "invalid_target", "Requested resource is not this MCP server")
            pending = PendingAuthorization(
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=request.query_params["state"],
                scopes=scopes,
                code_challenge=request.query_params["code_challenge"],
                code_challenge_method=request.query_params["code_challenge_method"],
                audience=self.config.oauth_audience,
                resource=resource,
            )
            if not pending.state.strip() or len(pending.state) > 512:
                return _error(
                    400,
                    "invalid_request",
                    "State is required and must not exceed 512 characters",
                )
            try:
                # Validate PKCE and all registered-client constraints before a
                # browser login is ever requested. The temporary code is not
                # issued here; validation is performed by a no-write mirror.
                if pending.code_challenge_method != "S256":
                    raise ValueError("PKCE S256 is required")
                import re

                if re.fullmatch(r"[A-Za-z0-9_-]{43,128}", pending.code_challenge) is None:
                    raise ValueError("PKCE S256 code challenge is invalid")
            except ValueError as exc:
                return _error(400, "invalid_request", str(exc))
            pending_handle = self.pending_authorizations.issue(pending)

        browser = self._browser_session(request)
        if browser is None:
            return self._connection_redirect(pending_handle)
        user, workspaces = await self._state_for_user(browser.user_id)
        if user is None:
            return _error(401, "browser_session_invalid", "Platform user no longer exists")
        if len(workspaces) != 1:
            return _error(
                409,
                "workspace_selection_required",
                "Exactly one live workspace membership is required for connection",
            )
        if await self._account_is_blocked(workspaces[0]):
            return _error(
                403,
                "account_access_blocked",
                "This workspace is not currently permitted to connect",
            )
        consumed = self.pending_authorizations.consume(pending_handle)
        if consumed is None:
            return _error(400, "invalid_request", "Authorization request is invalid or expired")
        try:
            code = await asyncio.to_thread(
                self.oauth.create_auth_code,
                workspaces[0],
                browser.user_id,
                consumed.client_id,
                consumed.redirect_uri,
                consumed.code_challenge,
                code_challenge_method=consumed.code_challenge_method,
                scopes=consumed.scopes,
                audience=consumed.audience,
                resource=consumed.resource,
            )
        except ValueError as exc:
            return _error(400, "invalid_request", str(exc))
        location = consumed.redirect_uri + ("&" if "?" in consumed.redirect_uri else "?") + urlencode(
            {"code": code, "state": consumed.state}
        )
        return RedirectResponse(location, status_code=303)

    async def browser_session(self, request: Request) -> JSONResponse:
        if self.human_identity_verifier is None:
            return self._with_connection_cors(request, _error(
                503,
                "human_identity_unconfigured",
                "Customer identity verification is not configured",
            ))
        header = request.headers.get("authorization", "")
        scheme, separator, token = header.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not token.strip():
            return self._with_connection_cors(
                request,
                _error(401, "human_identity_required", "Clerk bearer token is required"),
            )
        identity = await self.human_identity_verifier.verify_bearer(token.strip())
        if identity is None:
            return self._with_connection_cors(
                request,
                _error(401, "human_identity_invalid", "Clerk session is invalid or expired"),
            )
        try:
            user_id = await asyncio.to_thread(self.human_identities.resolve_or_bind, identity)
        except ValueError as exc:
            return self._with_connection_cors(
                request, _error(403, "identity_not_provisioned", str(exc))
            )
        user, workspaces = await self._state_for_user(user_id)
        if user is None:
            return self._with_connection_cors(
                request,
                _error(403, "identity_not_provisioned", "Platform user no longer exists"),
            )
        blocked = (
            len(workspaces) == 1
            and await self._account_is_blocked(workspaces[0])
        )
        issued = await asyncio.to_thread(self.browser_sessions.issue, user_id)
        connection: dict[str, Any] = {
            "status": (
                "access_blocked"
                if blocked
                else "ready"
                if len(workspaces) == 1
                else "workspace_resolution_required"
            ),
            "workspace_count": len(workspaces),
        }
        if len(workspaces) == 1:
            connection["workspace_id"] = workspaces[0]
        response = JSONResponse(
            {
                "user": user,
                "connection": connection,
                "csrf_token": issued.csrf_token,
                "expires_at": issued.expires_at.isoformat(),
            },
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            self.config.browser_cookie_name,
            issued.token,
            max_age=self.config.browser_session_ttl_seconds,
            httponly=True,
            secure=self.config.browser_cookie_secure,
            samesite="lax",
            path="/",
        )
        return self._with_connection_cors(request, response)

    async def browser_logout(self, request: Request) -> JSONResponse:
        token = request.cookies.get(self.config.browser_cookie_name, "")
        csrf = request.headers.get("x-csrf-token", "")
        if not token or not csrf or not self.browser_sessions.validate_csrf(token, csrf):
            return _error(403, "csrf_failed", "Valid browser session and CSRF token required")
        await asyncio.to_thread(self.browser_sessions.revoke, token)
        response = JSONResponse({"revoked": True}, headers={"Cache-Control": "no-store"})
        response.delete_cookie(
            self.config.browser_cookie_name,
            httponly=True,
            secure=self.config.browser_cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    async def _parse_form(self, request: Request) -> tuple[dict[str, str] | None, JSONResponse | None]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if content_type != "application/x-www-form-urlencoded":
            return None, _oauth_error(415, "invalid_request", "Form encoding is required")
        raw = await request.body()
        if len(raw) > 16 * 1024:
            return None, _oauth_error(413, "invalid_request", "OAuth form is too large")
        try:
            parsed = parse_qs(
                raw.decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=16,
            )
        except (UnicodeDecodeError, ValueError):
            return None, _oauth_error(400, "invalid_request", "OAuth form is invalid")
        if any(len(values) != 1 for values in parsed.values()):
            return None, _oauth_error(400, "invalid_request", "OAuth parameters cannot repeat")
        return {key: values[0] for key, values in parsed.items()}, None

    def _token_response(self, tokens) -> JSONResponse:
        session = self.oauth.validate_access(
            tokens.access_token,
            audience=self.config.oauth_audience,
            resource=self.config.oauth_resource,
        )
        if session is None:
            return _oauth_error(400, "invalid_grant", "Issued session is no longer valid")
        expires_in = max(
            0,
            int((tokens.access_expires_at - datetime.now(UTC)).total_seconds()),
        )
        return JSONResponse(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": "Bearer",
                "expires_in": expires_in,
                "scope": " ".join(session.scopes),
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    async def oauth_token(self, request: Request) -> JSONResponse:
        form, error = await self._parse_form(request)
        if error is not None:
            return error
        if AUTHORITY_SELECTORS.intersection(form):
            return _oauth_error(400, "invalid_request", "Server-owned authority cannot be selected")
        grant_type = form.get("grant_type")
        client_id = form.get("client_id", "")
        try:
            if grant_type == "authorization_code":
                required = ("code", "redirect_uri", "code_verifier")
                if not client_id or any(not form.get(key) for key in required):
                    raise ValueError("authorization code exchange parameters are required")
                tokens = await asyncio.to_thread(
                    self.oauth.exchange_code,
                    form["code"],
                    client_id,
                    form["redirect_uri"],
                    form["code_verifier"],
                )
            elif grant_type == "refresh_token":
                if not client_id or not form.get("refresh_token"):
                    raise ValueError("refresh token and client id are required")
                tokens = await asyncio.to_thread(
                    self.oauth.refresh_session,
                    form["refresh_token"],
                    client_id=client_id,
                )
                if tokens is None:
                    raise ValueError("refresh token is invalid or expired")
            else:
                return _oauth_error(400, "unsupported_grant_type", "Grant type is not supported")
        except ValueError as exc:
            return _oauth_error(400, "invalid_grant", str(exc))
        return self._token_response(tokens)

    async def oauth_revoke(self, request: Request) -> JSONResponse:
        form, error = await self._parse_form(request)
        if error is not None:
            return error
        token = form.get("token", "")
        client_id = form.get("client_id")
        if token:
            await asyncio.to_thread(self.oauth.revoke_token, token, client_id=client_id)
        return JSONResponse(
            {}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )

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

    def authorize_admin(
        self,
        request: Request,
        *,
        mutate: bool,
    ) -> tuple[AuthorityOutcome | None, JSONResponse | None]:
        outcome, error = self.authorize(
            request,
            scope=ADMIN_SCOPE,
            require_access=False,
        )
        if error is not None:
            return None, error
        if (
            outcome.internal_admin is None
            or outcome.internal_admin.role not in {"platform_admin", "support"}
        ):
            return None, _error(
                403,
                "forbidden",
                "Active internal operator authority is required",
            )
        if outcome.jv_grant_present:
            return None, _error(
                403,
                "forbidden",
                "JV identities cannot use internal admin routes",
            )
        if mutate and outcome.internal_admin.role != "platform_admin":
            return None, _error(
                403,
                "forbidden",
                "The support role is read-only",
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

    async def call_admin(self, function, /, *args, **kwargs):
        try:
            result = await asyncio.to_thread(function, *args, **kwargs)
        except AdminValidationError as exc:
            return None, _error(422, "invalid_request", str(exc))
        except AdminForbiddenError as exc:
            return None, _error(403, "forbidden", str(exc))
        except AdminNotFoundError as exc:
            return None, _error(404, "not_found", str(exc))
        except AdminConflictError as exc:
            return None, _error(409, "conflict", str(exc))
        except AdminAuditError:
            return None, _error(
                500,
                "admin_audit_failed",
                "Admin mutation could not be audited",
            )
        except ReconciliationValidationError as exc:
            return None, _error(422, "invalid_request", str(exc))
        except ReconciliationNotFoundError as exc:
            return None, _error(404, "not_found", str(exc))
        except ReconciliationConflictError as exc:
            return None, _error(409, "conflict", str(exc))
        return result, None

    async def _webhook(self, request: Request, provider: str) -> JSONResponse:
        if provider == "stripe":
            secret = self.config.stripe_webhook_secret
            header_name = "stripe-signature"
            parser = parse_stripe_event
        else:
            secret = self.config.skool_webhook_secret
            header_name = "x-skool-signature"
            parser = parse_skool_event
        if secret is None:
            return _error(
                404,
                "provider_not_configured",
                "Provider webhook is not configured",
            )

        maximum = self.config.provider_webhook_max_body_bytes
        content_lengths = request.headers.getlist("content-length")
        if len(content_lengths) > 1:
            return _error(
                400,
                "invalid_content_length",
                "Content-Length must be supplied at most once",
            )
        content_length = content_lengths[0] if content_lengths else None
        if content_length is not None:
            if (
                not content_length.isascii()
                or not content_length.isdecimal()
            ):
                return _error(
                    400,
                    "invalid_content_length",
                    "Content-Length must be a positive decimal integer",
                )
            declared_length = int(content_length)
            if declared_length <= 0:
                return _error(
                    400,
                    "invalid_content_length",
                    "Content-Length must be positive",
                )
            if declared_length > maximum:
                return _error(
                    413,
                    "webhook_body_too_large",
                    "Webhook body exceeds configured limit",
                )
        body_chunks: list[bytes] = []
        body_size = 0
        async for chunk in request.stream():
            next_size = body_size + len(chunk)
            if next_size > maximum:
                return _error(
                    413,
                    "webhook_body_too_large",
                    "Webhook body exceeds configured limit",
                )
            if chunk:
                body_chunks.append(chunk)
                body_size = next_size
        if content_length is not None and body_size != declared_length:
            return _error(
                400,
                "invalid_content_length",
                "Content-Length does not match the accepted body",
            )
        raw_body = b"".join(body_chunks)
        try:
            verify_hmac_signature(
                raw_body,
                request.headers.get(header_name, ""),
                secret,
            )
        except WebhookTimestampError:
            return _error(
                400,
                "webhook_timestamp_out_of_range",
                "Webhook timestamp is outside the accepted window",
            )
        except WebhookSignatureError:
            return _error(
                400,
                "invalid_webhook_signature",
                "Webhook signature is invalid",
            )

        try:
            envelope = decode_json_object(raw_body)
        except ProviderValidationError:
            identity = salvage_leading_identity(raw_body)
            if identity is not None:
                event_type = identity[1]
                type_is_safe = (
                    provider == "stripe"
                    and event_type in STRIPE_EVENT_TYPES
                ) or (
                    provider == "skool"
                    and event_type in SKOOL_EVENT_TYPES
                )
                if not type_is_safe:
                    identity = None
            if identity is not None:
                await asyncio.to_thread(
                    self.provider_sync.record_malformed,
                    provider,
                    identity,
                )
            return _error(
                400,
                "malformed_webhook",
                "Signed webhook body is not a valid provider envelope",
            )
        try:
            event = parser(envelope)
        except ProviderValidationError as exc:
            if (
                exc.durable
                and exc.event_id is not None
                and exc.event_type is not None
                and exc.occurred_at is not None
            ):
                result = await asyncio.to_thread(
                    self.provider_sync.record_malformed,
                    provider,
                    (exc.event_id, exc.event_type, exc.occurred_at),
                    exc.reason_code,
                )
                return JSONResponse(result.public(), status_code=202)
            return _error(
                400,
                "invalid_provider_envelope",
                "Signed webhook body is not a valid provider envelope",
            )
        result = await asyncio.to_thread(self.provider_sync.ingest, event)
        status = 202 if result.outcome == "quarantined" else 200
        return JSONResponse(result.public(), status_code=status)

    async def stripe_webhook(self, request: Request) -> JSONResponse:
        return await self._webhook(request, "stripe")

    async def skool_webhook(self, request: Request) -> JSONResponse:
        return await self._webhook(request, "skool")

    async def list_provider_quarantine(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=False)
        if error is not None:
            return error
        query = request.query_params
        result, error = await self.call_admin(
            self.provider_reconciliation.quarantine_queue,
            actor_user_id=authority.session.user_id,
            provider=query.get("provider"),
            limit=query.get("limit", "100"),
            cursor=query.get("cursor"),
            reason_code=request.headers.get("x-admin-reason-code"),
            reason=request.headers.get("x-admin-reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def replay_provider_event(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.provider_reconciliation.replay,
            actor_user_id=authority.session.user_id,
            provider_event_id=request.path_params["provider_event_id"],
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def list_workspace_provider_events(
        self,
        request: Request,
    ) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=False)
        if error is not None:
            return error
        query = request.query_params
        result, error = await self.call_admin(
            self.provider_reconciliation.workspace_events,
            actor_user_id=authority.session.user_id,
            workspace_public_id=request.path_params["workspace_id"],
            provider=query.get("provider"),
            limit=query.get("limit", "100"),
            cursor=query.get("cursor"),
            reason_code=request.headers.get("x-admin-reason-code"),
            reason=request.headers.get("x-admin-reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

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
        grants = []
        for grant in self.entitlements.list_grants(
            authority.workspace.public_id
        ):
            if grant.scope == "workspace":
                pass
            elif (
                grant.scope == "subject"
                and grant.subject_user_id == authority.session.user_id
            ):
                pass
            else:
                continue
            grants.append(
                {
                    "source": grant.source,
                    "profile": grant.profile,
                    "plan_key": grant.plan_key,
                    "status": grant.status,
                    "starts_at": grant.starts_at,
                    "ends_at": grant.ends_at,
                }
            )
        return JSONResponse(_jsonable({
            "account": authority.account,
            "effective_access": authority.effective_access,
            "access_enabled": authority.access_allowed,
            "grants": grants,
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

    async def provision_admin_workspace(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.provision_workspace,
            actor_user_id=authority.session.user_id,
            name=body.get("name"),
            slug=body.get("slug"),
            plan_id=body.get("plan_id"),
            owner_email=body.get("owner_email"),
            owner_name=body.get("owner_name"),
            account_state=body.get("account_state", "active"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result), status_code=201)

    async def get_admin_workspace(self, request: Request) -> JSONResponse:
        _, error = self.authorize_admin(request, mutate=False)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.get_workspace,
            request.path_params["workspace_id"],
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def update_admin_membership(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.update_membership_role,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            membership_id=request.path_params["membership_id"],
            role=body.get("role"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def create_admin_grant(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.create_grant,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            source=body.get("source"),
            external_ref=body.get("external_ref"),
            profile=body.get("profile"),
            plan_key=body.get("plan_key"),
            status=body.get("status", "active"),
            starts_at=body.get("starts_at"),
            ends_at=body.get("ends_at"),
            subject_user_id=body.get("subject_user_id"),
            scope=body.get("scope"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result), status_code=201)

    async def revoke_admin_grant(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.revoke_grant,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            grant_id=request.path_params["grant_id"],
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def create_admin_territory(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.create_territory,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            name=body.get("name"),
            state=body.get("state"),
            market=body.get("market"),
            asset_type=body.get("asset_type"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result), status_code=201)

    async def delete_admin_territory(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.delete_territory,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            territory_id=request.path_params["territory_id"],
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def create_admin_external_account(
        self,
        request: Request,
    ) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.create_external_account,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            provider=body.get("provider"),
            external_account_id=body.get("external_account_id"),
            subject_user_id=body.get("subject_user_id"),
            metadata=body.get("metadata"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result), status_code=201)

    async def list_admin_external_accounts(
        self,
        request: Request,
    ) -> JSONResponse:
        _, error = self.authorize_admin(request, mutate=False)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.list_external_accounts,
            request.path_params["workspace_id"],
        )
        if error is not None:
            return error
        return JSONResponse({"external_accounts": _jsonable(result)})

    async def delete_admin_external_account(
        self,
        request: Request,
    ) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.delete_external_account,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            mapping_id=request.path_params["mapping_id"],
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    async def update_admin_account_state(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_admin(request, mutate=True)
        if error is not None:
            return error
        body, error = await self.parse_json(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.set_account_state,
            actor_user_id=authority.session.user_id,
            public_id=request.path_params["workspace_id"],
            state=body.get("state"),
            reason_code=body.get("reason_code"),
            reason=body.get("reason"),
        )
        if error is not None:
            return error
        return JSONResponse(_jsonable(result))

    def authorize_jv(
        self,
        request: Request,
    ) -> tuple[AuthorityOutcome | None, JSONResponse | None]:
        authority, error = self.authorize(request)
        if error is not None:
            return None, error
        if (
            authority.effective_access is None
            or authority.effective_access.profile is not Profile.JV_PARTNER
        ):
            return None, _error(
                403,
                "forbidden",
                "The JV surface requires a live jv_partner profile",
            )
        if request.query_params:
            return None, _error(
                422,
                "invalid_scope_selector",
                "JV workspace, role, profile, and territory selectors are server-owned",
            )
        return authority, None

    async def get_jv_workspace(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_jv(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.get_jv_workspace,
            authority.workspace.public_id,
        )
        if error is not None:
            return error
        result["membership"] = _jsonable(authority.membership)
        return JSONResponse(_jsonable(result))

    async def list_jv_members(self, request: Request) -> JSONResponse:
        authority, error = self.authorize_jv(request)
        if error is not None:
            return error
        result, error = await self.call_admin(
            self.admin.list_members,
            authority.workspace.public_id,
        )
        if error is not None:
            return error
        return JSONResponse({"members": _jsonable(result)})

    def routes(self) -> list[Route]:
        """Starlette routes for this API, ready to mount under any prefix."""
        return [
            Route(path, getattr(self, handler), methods=list(methods))
            for path, methods, handler in PLATFORM_ROUTE_SPECS
        ]


# (path, methods, handler-name): the single source of truth for the platform
# HTTP surface, shared by ``PlatformApi.routes`` and the server's registration.
PLATFORM_ROUTE_SPECS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "/.well-known/oauth-authorization-server",
        ("GET",),
        "oauth_metadata",
    ),
    (
        "/.well-known/oauth-protected-resource",
        ("GET",),
        "protected_resource_metadata",
    ),
    ("/oauth/register", ("POST",), "oauth_register"),
    ("/oauth/authorize", ("GET",), "oauth_authorize"),
    ("/oauth/token", ("POST",), "oauth_token"),
    ("/oauth/revoke", ("POST",), "oauth_revoke"),
    ("/v1/browser/session", ("POST",), "browser_session"),
    ("/v1/browser/session", ("OPTIONS",), "browser_session_options"),
    ("/v1/browser/session", ("DELETE",), "browser_logout"),
    ("/v1/webhooks/stripe", ("POST",), "stripe_webhook"),
    ("/v1/webhooks/skool", ("POST",), "skool_webhook"),
    (
        "/v1/admin/provider-events/quarantine",
        ("GET",),
        "list_provider_quarantine",
    ),
    (
        "/v1/admin/provider-events/{provider_event_id:int}/replay",
        ("POST",),
        "replay_provider_event",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/provider-events",
        ("GET",),
        "list_workspace_provider_events",
    ),
    ("/v1/me", ("GET",), "me"),
    ("/v1/entitlements", ("GET",), "entitlement_summary"),
    ("/v1/deals", ("GET",), "list_deals"),
    ("/v1/deals", ("POST",), "create_deal"),
    ("/v1/deals/{deal_id:int}", ("GET",), "get_deal"),
    ("/v1/deals/{deal_id:int}", ("PATCH",), "update_deal"),
    ("/v1/admin/workspaces", ("POST",), "provision_admin_workspace"),
    (
        "/v1/admin/workspaces/{workspace_id}",
        ("GET",),
        "get_admin_workspace",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/memberships/{membership_id:int}",
        ("PATCH",),
        "update_admin_membership",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/grants",
        ("POST",),
        "create_admin_grant",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/grants/{grant_id:int}",
        ("DELETE",),
        "revoke_admin_grant",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/territories",
        ("POST",),
        "create_admin_territory",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/territories/{territory_id:int}",
        ("DELETE",),
        "delete_admin_territory",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/external-accounts",
        ("POST",),
        "create_admin_external_account",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/external-accounts",
        ("GET",),
        "list_admin_external_accounts",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/external-accounts/{mapping_id:int}",
        ("DELETE",),
        "delete_admin_external_account",
    ),
    (
        "/v1/admin/workspaces/{workspace_id}/account-state",
        ("POST",),
        "update_admin_account_state",
    ),
    ("/v1/jv/workspace", ("GET",), "get_jv_workspace"),
    ("/v1/jv/members", ("GET",), "list_jv_members"),
)


def starlette_app(
    config: CreConfig | None = None,
    *,
    human_identity_verifier: HumanIdentityVerifier | None = None,
) -> Starlette:
    """Build a standalone ASGI app for the customer-facing platform routes."""
    return Starlette(
        routes=PlatformApi(
            config,
            human_identity_verifier=human_identity_verifier,
        ).routes()
    )


__all__ = ["PLATFORM_ROUTE_SPECS", "PlatformApi", "starlette_app"]
