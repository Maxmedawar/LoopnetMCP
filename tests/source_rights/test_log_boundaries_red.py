"""Credential-redaction regressions for hosted logs and error boundaries."""

from __future__ import annotations

import importlib
import json
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from cre_mcp.access.context import use_context
from cre_mcp.command import tools as command_module
from cre_mcp.config import CreConfig
from cre_mcp.ledger import capture as capture_module
from cre_mcp.models import DisqualifierSpec, Rubric, SignalSpec
from cre_mcp.scoring import engine as scoring_module
from cre_mcp.sources.base import SearchQuery, SourceError
from cre_mcp.sources.distressed import county as county_module
from cre_mcp.sources.distressed.county import CountySource
from cre_mcp.truth.models import DocKind, DocumentRecord
from cre_mcp.truth.store import TruthStore


INPUT_SECRET = "hosted-input-secret-7e31"
ERROR_SECRET = "hosted-error-secret-2bf4"
INPUT_REFERENCE = f"https://example.test/deal?api_key={INPUT_SECRET}"
ERROR_MESSAGE = (
    "provider failed at "
    f"https://example.test/source?api_key={ERROR_SECRET} "
    f"Authorization: Bearer {ERROR_SECRET}"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "module_name",
        "function_name",
        "dependency_name",
        "method_name",
        "kwargs",
    ),
    [
        pytest.param(
            "cre_mcp.tools.memory_tools",
            "deal_timeline",
            "get_deal_store",
            "get_deal_timeline",
            {"deal_id": INPUT_REFERENCE},
            id="memory",
        ),
        pytest.param(
            "cre_mcp.tools.truth_tools",
            "list_deal_documents",
            "get_truth_store",
            "list_documents",
            {"deal_id": INPUT_REFERENCE},
            id="truth-tool",
        ),
        pytest.param(
            "cre_mcp.tools.ledger_tools",
            "record_lender_quote",
            "get_ledger_store",
            "record_quote",
            {"deal_id": INPUT_REFERENCE, "lender": INPUT_REFERENCE},
            id="ledger-tool",
        ),
        pytest.param(
            "cre_mcp.tools.capital_tools",
            "add_investor",
            "get_deal_store",
            "add_investor",
            {"name": INPUT_REFERENCE},
            id="capital-tool",
        ),
        pytest.param(
            "cre_mcp.tools.eval_tools",
            "record_deal_outcome",
            "get_deal_store",
            "record_outcome",
            {"deal_id": INPUT_REFERENCE, "closed": False},
            id="evaluation-tool",
        ),
    ],
)
async def test_hosted_tool_logs_and_error_payloads_redact_credentials(
    monkeypatch,
    caplog,
    module_name,
    function_name,
    dependency_name,
    method_name,
    kwargs,
):
    module = importlib.import_module(module_name)
    dependency = Mock()
    setattr(
        dependency,
        method_name,
        AsyncMock(side_effect=RuntimeError(ERROR_MESSAGE)),
    )
    monkeypatch.setattr(module, dependency_name, lambda: dependency)
    caplog.set_level(logging.INFO)

    with use_context(None):
        result = await getattr(module, function_name)(**kwargs)

    rendered = json.dumps(result)
    for secret in (INPUT_SECRET, ERROR_SECRET):
        assert secret not in caplog.text
        assert secret not in rendered


@pytest.mark.parametrize(
    "module_name",
    [
        "cre_mcp.analytics.tools",
        "cre_mcp.assetmgmt.tools",
        "cre_mcp.books.tools",
        "cre_mcp.closing.tools",
        "cre_mcp.construction.tools",
        "cre_mcp.finops.tools",
        "cre_mcp.fund.tools",
        "cre_mcp.leaseops.tools",
        "cre_mcp.mlops.tools",
        "cre_mcp.physical.tools",
        "cre_mcp.pmops.tools",
        "cre_mcp.relations.tools",
    ],
)
def test_registered_module_error_helpers_redact_credentials(
    module_name,
    caplog,
):
    module = importlib.import_module(module_name)
    caplog.set_level(logging.ERROR)

    with use_context(None):
        result = module._error("fixture", RuntimeError(ERROR_MESSAGE))

    assert ERROR_SECRET not in caplog.text
    assert ERROR_SECRET not in json.dumps(result)


def test_command_queue_logs_and_error_payload_redact_credentials(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        command_module,
        "morning_action_queue",
        Mock(side_effect=RuntimeError(ERROR_MESSAGE)),
    )
    caplog.set_level(logging.INFO)

    with use_context(None):
        result = command_module.morning_queue(INPUT_REFERENCE)

    for secret in (INPUT_SECRET, ERROR_SECRET):
        assert secret not in caplog.text
        assert secret not in json.dumps(result)


def test_scoring_failure_logs_and_notes_redact_credentials(
    monkeypatch,
    caplog,
):
    def fail(_context):
        raise RuntimeError(ERROR_MESSAGE)

    monkeypatch.setitem(
        scoring_module.DISQUALIFIER_PREDICATES,
        "redaction_predicate",
        fail,
    )
    monkeypatch.setitem(
        scoring_module.SIGNAL_EXTRACTORS,
        "redaction_signal",
        fail,
    )
    rubric = Rubric(
        strategy="redaction",
        display_name="Redaction",
        signals=[
            SignalSpec(
                key="redaction_signal",
                label="Redaction signal",
                extractor="redaction_signal",
                weight=1,
            )
        ],
        disqualifiers=[
            DisqualifierSpec(
                key="redaction_disqualifier",
                predicate="redaction_predicate",
                reason_template="not matched",
            )
        ],
        include_core=False,
        market_weight=0,
    )
    caplog.set_level(logging.WARNING)

    with use_context(None):
        assert scoring_module._disqualifier_hits(Mock(), rubric) == []
        evaluation = scoring_module._evaluate_signals(Mock(), rubric)

    note = evaluation.result.signal_results[0].note
    assert ERROR_SECRET not in caplog.text
    assert ERROR_SECRET not in str(note)


@pytest.mark.asyncio
async def test_county_source_log_and_error_boundary_redact_credentials(
    monkeypatch,
    caplog,
):
    source = CountySource()
    caplog.set_level(logging.INFO)

    with use_context(None):
        assert await source.search(SearchQuery(location=INPUT_REFERENCE)) == []

    monkeypatch.setattr(
        county_module,
        "arcgis_query",
        AsyncMock(side_effect=RuntimeError(ERROR_MESSAGE)),
    )
    with use_context(None), pytest.raises(SourceError) as raised:
        await source.search(SearchQuery(location="Guilford County, NC"))

    for secret in (INPUT_SECRET, ERROR_SECRET):
        assert secret not in caplog.text
        assert secret not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "list", "claims"])
async def test_truth_store_failure_logs_redact_credentials(
    monkeypatch,
    tmp_path,
    caplog,
    operation,
):
    store = TruthStore(
        CreConfig(_env_file=None, cache_db_path=tmp_path / "truth.db")
    )
    caplog.set_level(logging.ERROR)
    failure = RuntimeError(ERROR_MESSAGE)

    if operation == "save":
        monkeypatch.setattr(store, "_save_document", Mock(side_effect=failure))
        record = DocumentRecord(
            document_id="0" * 64,
            deal_id=INPUT_REFERENCE,
            doc_kind=DocKind.UNKNOWN,
            source_channel="uploaded",
            blob_path="",
            ingested_at="2026-08-01T00:00:00+00:00",
        )
        result = await store.save_document(record, b"test", [], ext="pdf")
        assert result is None
    elif operation == "list":
        monkeypatch.setattr(store, "_list_documents", Mock(side_effect=failure))
        assert await store.list_documents(INPUT_REFERENCE) == []
    else:
        monkeypatch.setattr(store, "_get_claims", Mock(side_effect=failure))
        assert await store.get_claims(INPUT_REFERENCE) == []

    for secret in (INPUT_SECRET, ERROR_SECRET):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_claim_capture_failure_does_not_emit_raw_traceback(
    monkeypatch,
    caplog,
):
    ledger_store = Mock()
    ledger_store.record_claims = AsyncMock(side_effect=RuntimeError(ERROR_MESSAGE))
    monkeypatch.setattr(
        capture_module,
        "claims_from_reconciliation",
        Mock(return_value=[Mock()]),
    )
    monkeypatch.setattr(
        capture_module,
        "get_ledger_store",
        lambda: ledger_store,
    )
    caplog.set_level(logging.ERROR)
    reconciliation = Mock(deal_id=INPUT_REFERENCE)

    with use_context(None):
        assert await capture_module.capture_reconciliation(reconciliation) == 0

    for secret in (INPUT_SECRET, ERROR_SECRET):
        assert secret not in caplog.text
    assert "Traceback" not in caplog.text
