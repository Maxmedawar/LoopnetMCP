from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from uuid import uuid4

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.shared.exceptions import McpError
from mcp.types import CallToolRequestParams

from cre_mcp.access.audit import AuditLog
from cre_mcp.access.context import TenantContext
from cre_mcp.access.engine import AccessEngine
from cre_mcp.access.middleware import AccessMiddleware, install_access
from cre_mcp.access.profiles import Profile
from cre_mcp.access.registry import WorkspaceRegistry
from cre_mcp.postgres.admission import AdmissionOutcome, AdmissionUnavailable
from tests.access.helpers import call_data, tool_names


def _context() -> TenantContext:
    return TenantContext(
        workspace_id="hosted-lifecycle",
        profile=Profile.FULL_OPERATOR,
        plan="pro",
        quota_limits={"search": 4},
        territories=("TX",),
        actor_id=str(uuid4()),
        session_id=str(uuid4()),
    )


def _outcome(
    context: TenantContext,
    tool_name: str,
    *,
    decision: str = "allowed",
    reason_code: str = "authority_admitted",
    safe_reason: str = "request admitted by live authority",
    approval_id: str | None = None,
    replayed: bool = False,
    finalized: bool = False,
) -> AdmissionOutcome:
    invocation_id = approval_id or str(uuid4())
    return AdmissionOutcome(
        invocation_id=invocation_id,
        request_correlation_id=str(uuid4()),
        workspace_public_id=context.workspace_id,
        actor_user_id=context.actor_id,
        session_id=context.session_id,
        tool_name=tool_name,
        decision=decision,
        reason_code=reason_code,
        safe_reason=safe_reason,
        approval_id=approval_id,
        replayed=replayed,
        finalized=finalized,
    )


class RecordingAdmission:
    def __init__(self, context: TenantContext) -> None:
        self.context = context
        self.admit_calls: list[dict] = []
        self.final_calls: list[dict] = []
        self.next_outcome: AdmissionOutcome | None = None
        self.admit_error: Exception | None = None
        self.final_error: Exception | None = None
        self.final_result = str(uuid4())

    def admit(
        self,
        context,
        tool_name,
        arguments,
        *,
        quota_bucket,
        requires_approval,
        approval_token=None,
        invocation_id=None,
        request_correlation_id=None,
    ):
        self.admit_calls.append(
            {
                "thread": threading.get_ident(),
                "context": context,
                "tool_name": tool_name,
                "arguments": arguments,
                "quota_bucket": quota_bucket,
                "requires_approval": requires_approval,
                "approval_token": approval_token,
                "invocation_id": invocation_id,
                "request_correlation_id": request_correlation_id,
            }
        )
        if self.admit_error is not None:
            raise self.admit_error
        outcome = self.next_outcome or _outcome(context, tool_name)
        invocation = str(invocation_id or outcome.invocation_id)
        return replace(
            outcome,
            invocation_id=invocation,
            request_correlation_id=str(
                request_correlation_id or outcome.request_correlation_id
            ),
            approval_id=(
                invocation
                if outcome.decision == "approval_required"
                else outcome.approval_id
            ),
        )

    def record_final(
        self,
        admission,
        *,
        succeeded,
        reason_code,
        safe_reason,
    ):
        self.final_calls.append(
            {
                "thread": threading.get_ident(),
                "admission": admission,
                "succeeded": succeeded,
                "reason_code": reason_code,
                "safe_reason": safe_reason,
            }
        )
        if self.final_error is not None:
            raise self.final_error
        return self.final_result


class RecordingAudit:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def record(self, **values):
        self.calls.append({"thread": threading.get_ident(), **values})
        if self.error is not None:
            raise self.error


class BlockingAdmission(RecordingAdmission):
    def __init__(self, context: TenantContext) -> None:
        super().__init__(context)
        self.started = threading.Event()
        self.release = threading.Event()

    def admit(self, *args, **kwargs):
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test admission was not released")
        return super().admit(*args, **kwargs)


class ReplayAwareAdmission(RecordingAdmission):
    def __init__(self, context: TenantContext) -> None:
        super().__init__(context)
        self._admissions: dict[str, AdmissionOutcome] = {}

    def admit(self, *args, **kwargs):
        outcome = super().admit(*args, **kwargs)
        invocation_id = outcome.invocation_id
        prior = self._admissions.get(invocation_id)
        if prior is not None:
            return replace(prior, replayed=True, finalized=True)
        self._admissions[invocation_id] = outcome
        return outcome


class StableRequestContext:
    class RequestContext:
        request_id = 71

    request_context = RequestContext()
    session_id = "mcp-session-stable-retry"


def _app(tmp_path, context, admission, *, failing: bool = False):
    app = FastMCP(name="hosted-admission-lifecycle")
    app.executions = 0
    app.received = None

    @app.tool
    async def save_deal(
        url_or_id: str,
        workspace_id: str | None = None,
        db_path: str | None = None,
    ) -> dict:
        app.executions += 1
        app.received = {
            "url_or_id": url_or_id,
            "workspace_id": workspace_id,
            "db_path": db_path,
        }
        if failing:
            raise RuntimeError("provider secret must-not-escape")
        return {"ok": True, "saved": url_or_id}

    uninstall = install_access(
        app,
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    return app, uninstall


async def test_hosted_admission_receives_only_sanitized_arguments_off_loop(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    app, uninstall = _app(tmp_path, context, admission)
    event_loop_thread = threading.get_ident()
    try:
        result = await call_data(
            app,
            "save_deal",
            {
                "url_or_id": "deal-1",
                "workspace_id": "smuggled",
                "db_path": "/tmp/smuggled.db",
                "_approval_id": "not-needed",
            },
        )
    finally:
        uninstall()

    assert result == {"ok": True, "saved": "deal-1"}
    assert app.received == {
        "url_or_id": "deal-1",
        "workspace_id": None,
        "db_path": None,
    }
    assert admission.admit_calls == [
        {
            "thread": admission.admit_calls[0]["thread"],
            "context": context,
            "tool_name": "save_deal",
            "arguments": {"url_or_id": "deal-1"},
            "quota_bucket": None,
            "requires_approval": False,
            "approval_token": None,
            "invocation_id": admission.admit_calls[0]["invocation_id"],
            "request_correlation_id": admission.admit_calls[0][
                "request_correlation_id"
            ],
        }
    ]
    assert admission.admit_calls[0]["invocation_id"] is not None
    assert admission.admit_calls[0]["request_correlation_id"] is not None
    assert admission.admit_calls[0]["thread"] != event_loop_thread
    assert admission.final_calls[0]["thread"] != event_loop_thread
    assert admission.final_calls[0]["succeeded"] is True
    assert admission.final_calls[0]["reason_code"] == "tool_completed"


async def test_hosted_approval_metadata_is_owned_by_atomic_admission(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    approval_id = str(uuid4())
    admission.next_outcome = _outcome(
        context,
        "generate_loi",
        decision="approval_required",
        reason_code="approval_required",
        safe_reason="sensitive action requires operator approval",
        approval_id=approval_id,
    )
    app = FastMCP(name="hosted-approval")
    app.executions = 0

    @app.tool
    async def generate_loi(deal_id: str) -> dict:
        app.executions += 1
        return {"ok": True, "deal_id": deal_id}

    uninstall = install_access(
        app,
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    try:
        result = await call_data(app, "generate_loi", {"deal_id": "deal-1"})
    finally:
        uninstall()

    assert result["approval_required"] is True
    assert result["approval_id"] == admission.admit_calls[0]["invocation_id"]
    assert app.executions == 0
    assert admission.admit_calls[0]["requires_approval"] is True
    assert admission.admit_calls[0]["approval_token"] is None
    assert admission.final_calls == []


@pytest.mark.parametrize("finalized", (False, True))
async def test_hosted_allowed_replay_never_executes(tmp_path, finalized) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    admission.next_outcome = _outcome(
        context,
        "save_deal",
        replayed=True,
        finalized=finalized,
    )
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="execution ownership"):
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert app.executions == 0
    assert admission.final_calls == []


async def test_duplicate_mcp_request_uses_one_stable_admission_binding(
    tmp_path,
) -> None:
    context = _context()
    admission = ReplayAwareAdmission(context)
    middleware = AccessMiddleware(
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    executions = 0

    async def execute(_context):
        nonlocal executions
        executions += 1
        return ToolResult(structured_content={"ok": True})

    def request_context():
        return MiddlewareContext(
            message=CallToolRequestParams(
                name="save_deal",
                arguments={"url_or_id": "deal-1"},
            ),
            fastmcp_context=StableRequestContext(),
            method="tools/call",
        )

    first = await middleware.on_call_tool(request_context(), execute)
    with pytest.raises(ToolError, match="execution ownership"):
        await middleware.on_call_tool(request_context(), execute)

    assert first.structured_content == {"ok": True}
    assert executions == 1
    assert len(admission.admit_calls) == 2
    assert admission.admit_calls[0]["invocation_id"] == admission.admit_calls[1][
        "invocation_id"
    ]
    assert admission.admit_calls[0]["request_correlation_id"] == (
        admission.admit_calls[1]["request_correlation_id"]
    )


async def test_hosted_denial_uses_atomic_safe_reason_without_execution(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    admission.next_outcome = _outcome(
        context,
        "save_deal",
        decision="denied",
        reason_code="quota_exceeded",
        safe_reason="access denied: daily quota exceeded",
    )
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="daily quota exceeded"):
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert app.executions == 0
    assert admission.final_calls == []


async def test_hosted_tool_failure_records_failed_final_before_safe_error(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    app, uninstall = _app(tmp_path, context, admission, failing=True)
    try:
        with pytest.raises(ToolError) as caught:
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert "must-not-escape" not in str(caught.value)
    assert admission.final_calls[0]["succeeded"] is False
    assert admission.final_calls[0]["reason_code"] == "tool_failed"


async def test_hosted_finalization_failure_withholds_successful_result(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    admission.final_error = AdmissionUnavailable("database secret")
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="finalization is unavailable") as caught:
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert "database secret" not in str(caught.value)
    assert app.executions == 1


async def test_hosted_admission_failure_is_safe_and_never_executes(tmp_path) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    admission.admit_error = AdmissionUnavailable("database secret")
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="admission is unavailable") as caught:
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert "database secret" not in str(caught.value)
    assert app.executions == 0
    assert admission.final_calls == []


@pytest.mark.parametrize("malformation", ("actor", "approval"))
async def test_malformed_admission_binding_fails_before_execution(
    tmp_path,
    malformation,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    outcome = _outcome(context, "save_deal")
    admission.next_outcome = (
        replace(outcome, actor_user_id=str(uuid4()))
        if malformation == "actor"
        else replace(outcome, approval_id=str(uuid4()))
    )
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="admission is unavailable"):
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert app.executions == 0
    assert admission.final_calls == []


async def test_malformed_final_audit_id_withholds_successful_result(tmp_path) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    admission.final_result = "not-a-uuid"
    app, uninstall = _app(tmp_path, context, admission)
    try:
        with pytest.raises(ToolError, match="finalization is unavailable"):
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert app.executions == 1


async def test_hosted_approval_token_is_removed_before_execution(tmp_path) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    app = FastMCP(name="hosted-approved-call")
    app.received = None

    @app.tool
    async def generate_loi(deal_id: str) -> dict:
        app.received = deal_id
        return {"ok": True, "deal_id": deal_id}

    uninstall = install_access(
        app,
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    token = str(uuid4())
    try:
        result = await call_data(
            app,
            "generate_loi",
            {"deal_id": "deal-1", "_approval_id": token},
        )
    finally:
        uninstall()

    assert result == {"ok": True, "deal_id": "deal-1"}
    assert admission.admit_calls[0]["arguments"] == {"deal_id": "deal-1"}
    assert admission.admit_calls[0]["requires_approval"] is True
    assert admission.admit_calls[0]["approval_token"] == token
    assert app.received == "deal-1"


def test_policy_only_check_never_mutates_local_approval_or_quota(tmp_path) -> None:
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    engine = AccessEngine(registry)
    context = _context().model_copy(update={"quota_limits": {"search": 0}})

    approval, approval_args = engine.check_call_policy(
        context,
        "generate_loi",
        {"deal_id": "deal-1"},
    )
    quota, quota_args = engine.check_call_policy(
        context,
        "search_properties",
        {"location": "Dallas, TX"},
    )

    assert approval.outcome == "allowed"
    assert approval_args == {"deal_id": "deal-1"}
    assert quota.outcome == "allowed"
    assert quota_args == {"location": "Dallas, TX"}
    assert registry._data["approvals"] == {}
    assert registry._data["usage"] == {}
    assert engine.call_admission_requirements(
        "generate_loi",
        approval_args,
    ) == (None, True)
    assert engine.call_admission_requirements(
        "search_properties",
        quota_args,
    ) == ("search", False)


async def test_hosted_policy_audit_runs_off_loop(tmp_path) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    audit = RecordingAudit()
    app = FastMCP(name="hosted-audit-thread")

    @app.tool
    async def save_deal(url_or_id: str) -> dict:
        return {"ok": True, "saved": url_or_id}

    uninstall = install_access(
        app,
        registry=None,
        audit_log=audit,
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    event_loop_thread = threading.get_ident()
    try:
        assert await tool_names(app) == {"save_deal"}
    finally:
        uninstall()

    assert audit.calls[0]["tool"] == "__list_tools__"
    assert audit.calls[0]["thread"] != event_loop_thread


async def test_hosted_policy_audit_failure_is_safe_and_fails_closed(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    audit = RecordingAudit(RuntimeError("audit database secret"))
    app = FastMCP(name="hosted-audit-failure")

    @app.tool
    async def save_deal(url_or_id: str) -> dict:
        return {"ok": True, "saved": url_or_id}

    uninstall = install_access(
        app,
        registry=None,
        audit_log=audit,
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    try:
        with pytest.raises(McpError, match="request audit is unavailable") as caught:
            await tool_names(app)
    finally:
        uninstall()

    assert "database secret" not in str(caught.value)


async def test_hosted_cancellation_records_failed_final(tmp_path) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    started = asyncio.Event()
    release = asyncio.Event()
    middleware = AccessMiddleware(
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )

    async def execute(_context):
        started.set()
        await release.wait()
        return ToolResult(structured_content={"ok": True})

    request = MiddlewareContext(
        message=CallToolRequestParams(
            name="save_deal",
            arguments={"url_or_id": "deal-1"},
        ),
        fastmcp_context=StableRequestContext(),
        method="tools/call",
    )
    task = asyncio.create_task(
        middleware.on_call_tool(request, execute)
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()

    assert admission.final_calls[0]["succeeded"] is False
    assert admission.final_calls[0]["reason_code"] == "request_cancelled"


async def test_cancellation_during_admission_never_orphans_fresh_allow(
    tmp_path,
) -> None:
    context = _context()
    admission = BlockingAdmission(context)
    middleware = AccessMiddleware(
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
    )
    task = asyncio.create_task(
        middleware._admit_hosted(
            context,
            "save_deal",
            {"url_or_id": "deal-1"},
            quota_bucket=None,
            requires_approval=False,
            approval_token=None,
            invocation_id=str(uuid4()),
            request_correlation_id=str(uuid4()),
        )
    )
    try:
        started = await asyncio.to_thread(admission.started.wait, 2)
        assert started
        task.cancel()
        admission.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        admission.release.set()

    assert admission.final_calls[0]["succeeded"] is False
    assert admission.final_calls[0]["reason_code"] == "request_cancelled"


async def test_grouped_argument_wrapper_failure_finalizes_without_execution(
    tmp_path,
) -> None:
    context = _context()
    admission = RecordingAdmission(context)
    app = FastMCP(name="hosted-wrapper-failure")
    app.executions = 0

    @app.tool
    async def save_deal(url_or_id: str) -> dict:
        app.executions += 1
        return {"ok": True, "saved": url_or_id}

    def resolve(tool_name, arguments):
        def fail_wrapper(_sanitized):
            raise RuntimeError("wrapper secret")

        return tool_name, dict(arguments or {}), fail_wrapper

    uninstall = install_access(
        app,
        registry=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        identity_resolver=lambda _context: context,
        runtime_mode="http",
        admission_repository=admission,
        tool_call_resolver=resolve,
    )
    try:
        with pytest.raises(ToolError, match="request setup failed") as caught:
            await call_data(app, "save_deal", {"url_or_id": "deal-1"})
    finally:
        uninstall()

    assert "wrapper secret" not in str(caught.value)
    assert app.executions == 0
    assert admission.final_calls[0]["succeeded"] is False
    assert admission.final_calls[0]["reason_code"] == "request_setup_failed"
