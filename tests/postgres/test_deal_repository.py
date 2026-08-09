from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg
import pytest

from cre_mcp.access.context import TenantContext, local_context, use_context
from cre_mcp.access.profiles import Profile
from cre_mcp.config import CreConfig
from cre_mcp.models.execution import DDItem
from cre_mcp.models.listings import Listing
from cre_mcp.postgres.admission import AdmissionOutcome
from cre_mcp.postgres.config import PostgresSettings
from cre_mcp.postgres.deals import (
    DealPersistenceUnavailable,
    PostgresDealRepository,
    _finish_thread_before_cancellation,
)
from cre_mcp.postgres.domains import (
    AdmittedRequestUnavailable,
    HostedRequestRepositories,
    use_hosted_request_repositories,
)
from cre_mcp.postgres.migrations import MigrationRunner
from cre_mcp.postgres.pool import PostgresDatabase


def _admission(
    tool_name: str,
    *,
    actor_user_id: str,
    workspace_public_id: str = "ws_deals_a",
) -> AdmissionOutcome:
    return AdmissionOutcome(
        invocation_id=str(uuid4()),
        request_correlation_id=str(uuid4()),
        workspace_public_id=workspace_public_id,
        actor_user_id=actor_user_id,
        session_id=str(uuid4()),
        tool_name=tool_name,
        decision="allowed",
        reason_code="authority_admitted",
        safe_reason="request admitted by live authority",
        replayed=False,
        finalized=False,
    )


def _context(admission: AdmissionOutcome) -> TenantContext:
    return TenantContext(
        workspace_id=admission.workspace_public_id,
        profile=Profile.FULL_OPERATOR,
        actor_id=admission.actor_user_id,
        session_id=admission.session_id,
        active=True,
        trusted=False,
    )


def _repositories(
    admission: AdmissionOutcome,
    deal: object,
) -> HostedRequestRepositories:
    marker = object()
    return HostedRequestRepositories(
        admission=admission,
        platform=marker,
        provider=marker,
        search=marker,
        deal=deal,
        privacy=marker,
        job=marker,
        document=marker,
        truth_asset=marker,
    )


@contextmanager
def _active(repository: object, admission: AdmissionOutcome):
    with use_context(_context(admission)), use_hosted_request_repositories(
        _repositories(admission, repository)
    ):
        yield


def _database(app_dsn: str) -> PostgresDatabase:
    database = PostgresDatabase(
        PostgresSettings(dsn=app_dsn, min_size=1, max_size=4, runtime_mode="app")
    )
    database.open()
    return database


def _rights_config(tmp_path: Path) -> CreConfig:
    source_path = (
        Path(__file__).parents[2]
        / "src"
        / "cre_mcp"
        / "source_rights"
        / "registry.json"
    )
    catalog = json.loads(source_path.read_text(encoding="utf-8"))
    record = next(
        item for item in catalog["sources"] if item["source_id"] == "listing.crexi"
    )
    record.update(
        {
            "rights_state": "CONDITIONAL",
            "hosted_cloud_allowed": True,
            "trusted_local_only": False,
            "official_evidence_urls": ["https://www.crexi.com/terms"],
            "evidence_verified_on": "2026-08-01",
            "evidence_status": "approved",
            "required_proofs": [],
            "disclosures": {
                "attribution": ["Test attribution"],
                "disclaimer": ["Test disclaimer"],
                "delivery_proven": True,
            },
        }
    )
    registry = tmp_path / f"deal-rights-{uuid4().hex}.json"
    registry.write_text(json.dumps(catalog), encoding="utf-8")
    return CreConfig(
        _env_file=None,
        transport="http",
        source_rights_registry_path=registry,
        source_rights_enabled={"listing.crexi": True},
    )


def _revoked_rights_config(tmp_path: Path) -> CreConfig:
    allowed = _rights_config(tmp_path)
    registry = json.loads(
        Path(allowed.source_rights_registry_path).read_text(encoding="utf-8")
    )
    record = next(
        item for item in registry["sources"] if item["source_id"] == "listing.crexi"
    )
    record["hosted_cloud_allowed"] = False
    revoked_path = tmp_path / f"deal-rights-revoked-{uuid4().hex}.json"
    revoked_path.write_text(json.dumps(registry), encoding="utf-8")
    return allowed.model_copy(update={"source_rights_registry_path": revoked_path})


def _listing(source_id: str, *, state: str = "CA", price: float = 2_500_000) -> Listing:
    return Listing(
        source="crexi",
        source_id=source_id,
        name=f"Property {source_id}",
        address="100 Main Street",
        city="Los Angeles" if state == "CA" else "Austin",
        state=state,
        zip_code="90001" if state == "CA" else "78701",
        property_type="retail",
        listing_type="for-sale",
        price=f"${price:,.0f}",
        price_usd=price,
        url=f"https://www.crexi.com/properties/{source_id}",
    )


def _seed(
    postgres_database: tuple[str, str, str],
    admissions: tuple[AdmissionOutcome, ...],
) -> tuple[str, str, PostgresDatabase]:
    admin_dsn, migration_dsn, app_dsn = postgres_database
    MigrationRunner(migration_dsn).apply()
    workspace_id = str(uuid4())
    actor_ids = tuple(dict.fromkeys(item.actor_user_id for item in admissions))
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,%s,'Deal Workspace','active')",
            (workspace_id, admissions[0].workspace_public_id),
        )
        for actor_id in actor_ids:
            connection.execute(
                "INSERT INTO medawarcre.users(id,email,name,state) "
                "VALUES (%s,%s,'Deal Actor','active')",
                (actor_id, f"deals-{uuid4().hex}@example.test"),
            )
            connection.execute(
                "INSERT INTO medawarcre.memberships("
                "id,workspace_id,user_id,role,state) "
                "VALUES (%s,%s,%s,'owner','active')",
                (str(uuid4()), workspace_id, actor_id),
            )
        for admission in admissions:
            connection.execute(
                "INSERT INTO medawarcre.access_decision_audit("
                "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
                "session_correlation_hash,request_correlation_id,tool_name,decision,"
                "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
                "%s,'admission',true,%s,%s,"
                "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
                "'authority_admitted','request admitted by live authority',"
                "decode(repeat('41',32),'hex'),decode(repeat('42',32),'hex'))",
                (
                    admission.invocation_id,
                    workspace_id,
                    admission.actor_user_id,
                    admission.session_id,
                    admission.request_correlation_id,
                    admission.tool_name,
                ),
            )
    return admin_dsn, workspace_id, _database(app_dsn)


def _repository(
    database: PostgresDatabase,
    admission: AdmissionOutcome,
    config: CreConfig,
) -> PostgresDealRepository:
    return PostgresDealRepository(database, admission, config=config)


@pytest.mark.asyncio
async def test_pipeline_capabilities_are_atomic_attributed_and_historic(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    add = _admission("add_to_pipeline", actor_user_id=actor_id)
    update = _admission("update_deal_stage", actor_user_id=actor_id)
    assign = _admission("assign_deal", actor_user_id=actor_id)
    listing = _admission("list_pipeline", actor_user_id=actor_id)
    admissions = (add, update, assign, listing)
    admin_dsn, workspace_id, database = _seed(postgres_database, admissions)
    config = _rights_config(tmp_path)
    try:
        add_repository = _repository(database, add, config)
        with _active(add_repository, add):
            row = await add_repository.add_to_pipeline_result(
                _listing("pipeline-1"),
                score=87.5,
                grade="A",
                strategy="nnn_retail",
                stage="analyzing",
                note="Initial review",
            )
        assert row["deal_id"] == "crexi:pipeline-1"
        assert row["stage"] == "analyzing"
        assert row["last_note"]["text"] == "Initial review"
        assert row["last_note"]["stage"] == "analyzing"

        update_repository = _repository(database, update, config)
        with _active(update_repository, update):
            updated = await update_repository.update_stage_result(
                row["deal_id"],
                "contacted",
                "Broker contacted",
            )
        assert updated is not None
        assert updated["stage"] == "contacted"
        assert [note["stage"] for note in updated["notes"]] == [
            "analyzing",
            "contacted",
        ]

        assign_repository = _repository(database, assign, config)
        with _active(assign_repository, assign):
            accountability = await assign_repository.assign_deal(
                row["deal_id"],
                owner="Max",
                next_action="Review rent roll",
                next_action_due="2026-08-15",
            )
        assert accountability is not None
        assert accountability["next_action_due"].startswith("2026-08-15T00:00:00")

        list_repository = _repository(database, listing, config)
        with _active(list_repository, listing):
            rows = await list_repository.list_pipeline()
        assert [item["deal_id"] for item in rows] == ["crexi:pipeline-1"]

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            stored = connection.execute(
                "SELECT owner_user_id,created_by_user_id::text,updated_by_user_id::text,"
                "source_rights_id,source_rights_verified_on::text "
                "FROM medawarcre.deals WHERE workspace_id=%s",
                (workspace_id,),
            ).fetchone()
            stages = connection.execute(
                "SELECT stage FROM medawarcre.deal_notes "
                "WHERE workspace_id=%s ORDER BY created_at,id",
                (workspace_id,),
            ).fetchall()
        assert stored == (
            None,
            actor_id,
            actor_id,
            "listing.crexi",
            "2026-08-01",
        )
        assert stages == [("analyzing",), ("contacted",)]
    finally:
        database.close()


@pytest.mark.asyncio
async def test_deal_subdomains_use_uuid_ids_frozen_predictions_and_idempotency(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    tools = (
        "save_deal",
        "due_diligence_plan",
        "operating_playbook",
        "record_deal_outcome",
        "add_investor",
        "record_commitment",
        "start_exchange",
        "identify_replacement",
        "record_ic_decision",
        "log_deal_event",
        "deal_timeline",
        "ic_scorecard",
    )
    admissions = tuple(_admission(tool, actor_user_id=actor_id) for tool in tools)
    by_tool = {item.tool_name: item for item in admissions}
    admin_dsn, workspace_id, database = _seed(postgres_database, admissions)
    config = _rights_config(tmp_path)
    repositories = {
        tool: _repository(database, admission, config)
        for tool, admission in by_tool.items()
    }
    try:
        save = repositories["save_deal"]
        with _active(save, by_tool["save_deal"]):
            deal_id = await save.save_deal(
                _listing("primary"),
                score=88,
                grade="A",
                strategy="nnn_retail",
            )
            replacement_id = await save.save_deal(_listing("replacement", price=3_000_000))
            other_replacements = [
                await save.save_deal(
                    _listing(f"replacement-{index}", price=3_000_000)
                )
                for index in range(2, 5)
            ]

        diligence = repositories["due_diligence_plan"]
        item = DDItem(
            key="title",
            label="Title review",
            why="Confirm ownership",
            what_clears_it="Counsel approval",
            what_should_make_you_terminate="Uncured defect",
            who_to_hire="CRE counsel",
            due_offset_days=5,
            deadline=date(2026, 8, 20),
        )
        with _active(diligence, by_tool["due_diligence_plan"]):
            diligence_result = await diligence.replace_diligence(
                _listing("primary"),
                [item],
            )
        assert diligence_result["deal_id"] == deal_id
        assert diligence_result["items"][0]["key"] == "title"

        operating = repositories["operating_playbook"]
        with _active(operating, by_tool["operating_playbook"]):
            operating_result = await operating.replace_operating(
                _listing("primary"),
                [
                    {
                        "key": "month-one",
                        "category": "month_one",
                        "status": "not_started",
                        "event_date": "2026-09-01",
                    }
                ],
            )
        assert operating_result["deal_id"] == deal_id

        outcome_repository = repositories["record_deal_outcome"]
        with _active(outcome_repository, by_tool["record_deal_outcome"]):
            outcome = await outcome_repository.record_outcome_result(
                deal_id,
                {"closed": True, "purchase_price": 2_400_000, "went_bad": False},
            )
            assert outcome is not None
            assert outcome["predicted_score"] == 88
            outcome = await outcome_repository.record_outcome_result(
                deal_id,
                {"closed": True, "purchase_price": 2_350_000, "went_bad": False},
            )
        assert outcome is not None
        assert outcome["predicted_score"] == 88
        assert outcome["purchase_price"] == 2_350_000

        investor_repository = repositories["add_investor"]
        with _active(investor_repository, by_tool["add_investor"]):
            investor = await investor_repository.add_investor_result(
                "Investor One",
                accredited=True,
                relationship="preexisting",
            )
        assert len(investor["investor_id"]) == 36

        commitment_repository = repositories["record_commitment"]
        with _active(commitment_repository, by_tool["record_commitment"]):
            commitment = await commitment_repository.record_commitment_result(
                deal_id,
                investor["investor_id"],
                500_000,
            )
        assert commitment is not None
        assert len(commitment["commitment_id"]) == 36

        exchange_repository = repositories["start_exchange"]
        with _active(exchange_repository, by_tool["start_exchange"]):
            exchange = await exchange_repository.create_exchange_result(
                deal_id,
                "2026-08-01",
                "2026-09-15",
                "2027-01-28",
            )
        assert exchange is not None
        exchange_id = exchange["exchange_id"]
        assert len(exchange["exchange_id"]) == 36

        replacement_repository = repositories["identify_replacement"]
        with _active(replacement_repository, by_tool["identify_replacement"]):
            exchange = await replacement_repository.identify_exchange_replacement_result(
                exchange_id,
                replacement_id,
                "2026-08-10",
            )
        assert exchange is not None
        assert exchange["replacements"][0]["deal_id"] == replacement_id
        with _active(replacement_repository, by_tool["identify_replacement"]):
            for candidate_id in other_replacements[:2]:
                exchange = await replacement_repository.identify_exchange_replacement_result(
                    exchange_id,
                    candidate_id,
                    "2026-08-11",
                )
            with pytest.raises(ValueError, match="exceeding the 200% ceiling"):
                await replacement_repository.identify_exchange_replacement_result(
                    exchange_id,
                    other_replacements[2],
                    "2026-08-12",
                )
            with pytest.raises(ValueError, match="locked after day 45"):
                await replacement_repository.identify_exchange_replacement_result(
                    exchange_id,
                    replacement_id,
                    "2026-09-16",
                )
        assert len(exchange["replacements"]) == 3

        decision_repository = repositories["record_ic_decision"]
        with _active(decision_repository, by_tool["record_ic_decision"]):
            first_decision = await decision_repository.record_ic_decision(
                deal_id,
                system_verdict="proceed",
                system={"score": 88},
                expert_verdict="proceed",
                expert={"reviewer": "operator"},
            )
            second_decision = await decision_repository.record_ic_decision(
                deal_id,
                system_verdict="proceed",
                system={"score": 88},
                expert_verdict="proceed",
                expert={"reviewer": "operator"},
            )
        assert first_decision == second_decision

        event_repository = repositories["log_deal_event"]
        with _active(event_repository, by_tool["log_deal_event"]):
            first_event = await event_repository.log_deal_event(
                deal_id,
                "inspection_complete",
                {"result": "clear"},
            )
            second_event = await event_repository.log_deal_event(
                deal_id,
                "inspection_complete",
                {"result": "clear"},
            )
        assert first_event == second_event

        timeline_repository = repositories["deal_timeline"]
        with _active(timeline_repository, by_tool["deal_timeline"]):
            timeline = await timeline_repository.get_deal_timeline(deal_id)
        assert len(timeline["events"]) == 1
        assert len(timeline["ic_decisions"]) == 1

        scorecard_repository = repositories["ic_scorecard"]
        with _active(scorecard_repository, by_tool["ic_scorecard"]):
            scorecard = await scorecard_repository.ic_scorecard()
        assert scorecard["total_ic_decisions"] == 1
        assert scorecard["system_expert_agreement_rate"] == 1.0
        assert scorecard["system_accuracy_vs_outcome"] == 1.0

        deal_relations = (
            "deal_notes",
            "deal_outcomes",
            "deal_events",
            "deal_dd_items",
            "deal_ops_events",
            "deal_investors",
            "deal_commitments",
            "deal_exchanges",
            "deal_exchange_replacements",
            "deal_ic_decisions",
            "deals",
        )
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "ALTER TABLE medawarcre.access_decision_audit DISABLE TRIGGER USER"
            )
            connection.execute(
                "DELETE FROM medawarcre.access_decision_audit WHERE workspace_id=%s",
                (workspace_id,),
            )
            connection.execute(
                "ALTER TABLE medawarcre.access_decision_audit ENABLE TRIGGER USER"
            )
            connection.execute(
                "DELETE FROM medawarcre.workspaces WHERE id=%s",
                (workspace_id,),
            )
            for relation_name in deal_relations:
                assert connection.execute(
                    f"SELECT count(*) FROM medawarcre.{relation_name} "
                    "WHERE workspace_id=%s",
                    (workspace_id,),
                ).fetchone()[0] == 0
    finally:
        database.close()


@pytest.mark.asyncio
async def test_repository_requires_exact_active_aggregate_actor_and_session(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    admission = _admission("list_deals", actor_user_id=str(uuid4()))
    _, _, database = _seed(postgres_database, (admission,))
    repository = _repository(database, admission, _rights_config(tmp_path))
    try:
        context = _context(admission)
        with use_context(context), use_hosted_request_repositories(
            _repositories(admission, object())
        ):
            with pytest.raises(DealPersistenceUnavailable):
                await repository.list_deals()

        for altered in (
            context.model_copy(update={"actor_id": str(uuid4())}),
            context.model_copy(update={"session_id": str(uuid4())}),
            context.model_copy(update={"workspace_id": "ws_wrong"}),
            context.model_copy(update={"active": False}),
        ):
            with use_context(altered), use_hosted_request_repositories(
                _repositories(admission, repository)
            ):
                with pytest.raises(DealPersistenceUnavailable):
                    await repository.list_deals()

        with _active(repository, admission):
            assert await repository.list_deals() == []
    finally:
        database.close()


@pytest.mark.asyncio
async def test_workspace_collaboration_isolated_cross_object_uuid_rejected(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_a, actor_b, actor_c = (str(uuid4()) for _ in range(3))
    save_a = _admission("save_deal", actor_user_id=actor_a, workspace_public_id="ws_deals_a")
    list_b = _admission("list_deals", actor_user_id=actor_b, workspace_public_id="ws_deals_a")
    commit_a = _admission(
        "record_commitment",
        actor_user_id=actor_a,
        workspace_public_id="ws_deals_a",
    )
    save_c = _admission("save_deal", actor_user_id=actor_c, workspace_public_id="ws_deals_b")
    investor_c = _admission(
        "add_investor",
        actor_user_id=actor_c,
        workspace_public_id="ws_deals_b",
    )
    _, _, database_a = _seed(postgres_database, (save_a, list_b, commit_a))
    _, _, database_b = _seed(postgres_database, (save_c, investor_c))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database_a, save_a, config)
        with _active(repository, save_a):
            visible_deal = await repository.save_deal(_listing("shared-visible"))

        repository = _repository(database_b, save_c, config)
        with _active(repository, save_c):
            await repository.save_deal(_listing("other-workspace"))

        repository = _repository(database_b, investor_c, config)
        with _active(repository, investor_c):
            hidden_investor = await repository.add_investor_result(
                "Other Workspace Investor",
                accredited=True,
                relationship="preexisting",
            )

        repository = _repository(database_a, list_b, config)
        with _active(repository, list_b):
            rows = await repository.list_deals()
        assert [row["deal_id"] for row in rows] == [visible_deal]

        repository = _repository(database_a, commit_a, config)
        with _active(repository, commit_a):
            assert await repository.record_commitment_result(
                visible_deal,
                hidden_investor["investor_id"],
                250_000,
            ) is None
    finally:
        database_a.close()
        database_b.close()


@pytest.mark.asyncio
async def test_live_source_revocation_and_jv_territory_filter_fail_closed(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    list_admission = _admission("list_deals", actor_user_id=actor_id)
    noi = _admission("build_noi_bridge", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, list_admission, noi))
    allowed = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, allowed)
        with _active(repository, save):
            await repository.save_deal(_listing("territory-ca"))
            await repository.save_deal(_listing("territory-tx", state="TX"))

        territory_context = _context(list_admission).model_copy(
            update={"profile": Profile.JV_PARTNER, "territories": ("CA",)}
        )
        repository = _repository(database, list_admission, allowed)
        with use_context(territory_context), use_hosted_request_repositories(
            _repositories(list_admission, repository)
        ):
            rows = await repository.list_deals()
        assert [row["deal_id"] for row in rows] == ["crexi:territory-ca"]

        noi_context = _context(noi).model_copy(
            update={"profile": Profile.JV_PARTNER, "territories": ("CA",)}
        )
        repository = _repository(database, noi, allowed)
        with use_context(noi_context), use_hosted_request_repositories(
            _repositories(noi, repository)
        ):
            with pytest.raises(DealPersistenceUnavailable):
                await repository.get_deal("crexi:territory-tx")

        revoked = _revoked_rights_config(tmp_path)
        repository = _repository(database, list_admission, revoked)
        with _active(repository, list_admission):
            with pytest.raises(DealPersistenceUnavailable):
                await repository.list_deals()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_malformed_outcome_row_is_rejected_on_read(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    record = _admission("record_deal_outcome", actor_user_id=actor_id)
    read = _admission("backtest_score", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save, record, read))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            deal_id = await repository.save_deal(_listing("malformed-outcome"), score=80)
        repository = _repository(database, record, config)
        with _active(repository, record):
            await repository.record_outcome_result(
                deal_id,
                {"closed": True, "purchase_price": 2_400_000},
            )

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "ALTER TABLE medawarcre.deal_outcomes "
                "DROP CONSTRAINT deal_outcomes_closed_price_check"
            )
            connection.execute(
                "UPDATE medawarcre.deal_outcomes SET purchase_price=NULL "
                "WHERE workspace_id=%s",
                (workspace_id,),
            )

        repository = _repository(database, read, config)
        with _active(repository, read):
            with pytest.raises(DealPersistenceUnavailable):
                await repository.get_outcomes()
    finally:
        database.close()


@pytest.mark.asyncio
async def test_diligence_composite_rolls_back_deal_refresh_on_child_failure(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    diligence = _admission("due_diligence_plan", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save, diligence))
    config = _rights_config(tmp_path)
    original = _listing("rollback")
    changed = original.model_copy(update={"name": "Uncommitted Refresh"})
    item = DDItem(
        key="title",
        label="Title review",
        why="Confirm ownership",
        what_clears_it="Counsel approval",
        what_should_make_you_terminate="Uncured defect",
        who_to_hire="CRE counsel",
        due_offset_days=5,
        deadline=date(2026, 8, 20),
    )
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(original)

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "CREATE FUNCTION medawarcre.reject_test_dd_item() RETURNS trigger "
                "LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'injected child failure'; END$$"
            )
            connection.execute(
                "CREATE TRIGGER reject_test_dd_item BEFORE INSERT "
                "ON medawarcre.deal_dd_items FOR EACH ROW "
                "EXECUTE FUNCTION medawarcre.reject_test_dd_item()"
            )

        repository = _repository(database, diligence, config)
        with _active(repository, diligence):
            with pytest.raises(DealPersistenceUnavailable):
                await repository.replace_diligence(changed, [item])

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            stored = connection.execute(
                "SELECT title,listing->>'name' FROM medawarcre.deals "
                "WHERE workspace_id=%s",
                (workspace_id,),
            ).fetchone()
            item_count = connection.execute(
                "SELECT count(*) FROM medawarcre.deal_dd_items WHERE workspace_id=%s",
                (workspace_id,),
            ).fetchone()[0]
        assert stored == (original.name, original.name)
        assert item_count == 0
    finally:
        database.close()


@pytest.mark.asyncio
async def test_concurrent_event_retry_is_idempotent(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    event = _admission("log_deal_event", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save, event))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            deal_id = await repository.save_deal(_listing("event-race"))

        repository = _repository(database, event, config)
        with _active(repository, event):
            first, second = await asyncio.gather(
                repository.log_deal_event(deal_id, "inspection_complete", {"ok": True}),
                repository.log_deal_event(deal_id, "inspection_complete", {"ok": True}),
            )
        assert first == second
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            assert connection.execute(
                "SELECT count(*) FROM medawarcre.deal_events WHERE workspace_id=%s",
                (workspace_id,),
            ).fetchone()[0] == 1
    finally:
        database.close()


@pytest.mark.asyncio
async def test_app_cannot_erase_rights_evidence_or_store_nonfinite_price(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save,))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(_listing("rights-evidence"))
            with database.admitted_connection(save) as connection:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute(
                            "UPDATE medawarcre.deals SET source_rights_id=NULL,"
                            "source_rights_verified_on=NULL,updated_by_user_id="
                            "medawarcre.current_actor_user_id() WHERE source='crexi' "
                            "AND source_record_id='rights-evidence'"
                        )

        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "UPDATE medawarcre.deals SET asking_price='NaN'::numeric "
                    "WHERE workspace_id=%s",
                    (workspace_id,),
                )
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            assert connection.execute(
                "SELECT source_rights_id,source_rights_verified_on::text "
                "FROM medawarcre.deals WHERE workspace_id=%s",
                (workspace_id,),
            ).fetchone() == ("listing.crexi", "2026-08-01")
    finally:
        database.close()


@pytest.mark.asyncio
async def test_cancellation_waits_for_database_worker_to_finish() -> None:
    started = Event()
    release = Event()
    finished = Event()

    def operation() -> str:
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "done"

    task = asyncio.create_task(_finish_thread_before_cancellation(operation))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not finished.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_deal_factory_denies_untrusted_fallback_and_detached_ports(
    tmp_path: Path,
) -> None:
    from cre_mcp.deals.store import DealStore, get_deal_store

    config = CreConfig(_env_file=None, cache_db_path=tmp_path / "local.db")
    with use_context(local_context()):
        assert isinstance(get_deal_store(config), DealStore)

    admission = _admission("list_deals", actor_user_id=str(uuid4()))
    hosted = object()
    with _active(hosted, admission):
        assert get_deal_store(config) is hosted
        with pytest.raises(
            AdmittedRequestUnavailable,
            match="^deal persistence unavailable$",
        ):
            DealStore(config=config)

    with use_context(_context(admission)):
        with pytest.raises(
            AdmittedRequestUnavailable,
            match="^deal persistence unavailable$",
        ):
            get_deal_store(config)
        with pytest.raises(
            AdmittedRequestUnavailable,
            match="^deal persistence unavailable$",
        ):
            DealStore(config=config)
    assert not (tmp_path / "local.db").exists()


def test_phase_5g_repository_contract_is_importable() -> None:
    assert issubclass(DealPersistenceUnavailable, RuntimeError)
    assert PostgresDealRepository.__name__ == "PostgresDealRepository"


@pytest.mark.asyncio
async def test_ordinary_source_data_is_stored_not_rejected(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Real listings must not hard-fail on write-only denormalized columns.

    ``title`` and ``asking_price`` are denormalized copies the app role cannot
    even select; every read projects from the bounded listing JSON.  Real source
    mappers emit zero or negative prices and very long names, and the local
    store accepts them, so hosted saves must normalize rather than abort with
    the fixed opaque error.
    """
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    read = _admission("list_deals", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save, read))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            zero = await repository.save_deal(_listing("zero-price", price=0))
            negative = await repository.save_deal(_listing("negative-price", price=-1))
            long_name = _listing("long-name")
            oversized = long_name.model_copy(update={"name": "N" * 640})
            named = await repository.save_deal(oversized)

        assert zero == "crexi:zero-price"
        assert negative == "crexi:negative-price"
        assert named == "crexi:long-name"

        repository = _repository(database, read, config)
        with _active(repository, read):
            rows = {row["deal_id"]: row for row in await repository.list_deals()}
        assert set(rows) == {
            "crexi:zero-price", "crexi:negative-price", "crexi:long-name",
        }
        # The authoritative name survives in the listing JSON even though the
        # denormalized column is bounded.
        assert rows["crexi:long-name"]["name"] == "N" * 640

        with psycopg.connect(admin_dsn) as connection:
            stored = dict(
                connection.execute(
                    "SELECT source_record_id,asking_price FROM medawarcre.deals "
                    "WHERE workspace_id=%s",
                    (workspace_id,),
                ).fetchall()
            )
            title_length = connection.execute(
                "SELECT length(title) FROM medawarcre.deals "
                "WHERE workspace_id=%s AND source_record_id='long-name'",
                (workspace_id,),
            ).fetchone()[0]
        assert stored["zero-price"] is None
        assert stored["negative-price"] is None
        assert title_length <= 500
    finally:
        database.close()


@pytest.mark.asyncio
async def test_admission_cannot_call_a_method_its_capability_does_not_need(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Method authority is closed by default, per the phase contract."""
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    outcome = _admission("record_deal_outcome", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, outcome))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            # `save_deal` is entitled to save, and to nothing else.
            await repository.save_deal(_listing("authority-probe"))
            for denied in (
                repository.list_deals(),
                repository.list_pipeline(),
                repository.unaccounted_deals(),
                repository.get_outcomes(),
                repository.list_investors(),
                repository.ic_scorecard(),
                repository.get_deal("crexi:authority-probe"),
            ):
                with pytest.raises(DealPersistenceUnavailable):
                    await denied

        # The composite hosted path is the only route to these legacy scalars,
        # so they stay permanently closed rather than merely unused.
        repository = _repository(database, outcome, config)
        with _active(repository, outcome):
            for closed in (
                repository.update_stage("crexi:authority-probe", "loi"),
                repository.get_dd_items("crexi:authority-probe"),
                repository.create_exchange(
                    "crexi:authority-probe", "2026-01-01", "2026-02-15", "2026-06-30"
                ),
            ):
                with pytest.raises(DealPersistenceUnavailable):
                    await closed
    finally:
        database.close()


@pytest.mark.asyncio
async def test_same_source_record_is_isolated_across_workspaces(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """The identical source:record_id in two workspaces must never cross over."""
    actor_a, actor_b = str(uuid4()), str(uuid4())
    save_a = _admission("save_deal", actor_user_id=actor_a, workspace_public_id="ws_deals_a")
    read_a = _admission("list_deals", actor_user_id=actor_a, workspace_public_id="ws_deals_a")
    save_b = _admission("save_deal", actor_user_id=actor_b, workspace_public_id="ws_deals_b")
    stage_b = _admission("update_deal_stage", actor_user_id=actor_b, workspace_public_id="ws_deals_b")
    read_b = _admission("list_deals", actor_user_id=actor_b, workspace_public_id="ws_deals_b")
    _, _, database_a = _seed(postgres_database, (save_a, read_a))
    _, _, database_b = _seed(postgres_database, (save_b, stage_b, read_b))
    config = _rights_config(tmp_path)
    try:
        shared = "identical-record"
        repository = _repository(database_a, save_a, config)
        with _active(repository, save_a):
            await repository.save_deal(_listing(shared, state="CA"))
        repository = _repository(database_b, save_b, config)
        with _active(repository, save_b):
            await repository.save_deal(_listing(shared, state="TX"))

        # Workspace B mutating its copy must not touch workspace A's.
        repository = _repository(database_b, stage_b, config)
        with _active(repository, stage_b):
            moved = await repository.update_stage_result(f"crexi:{shared}", "loi")
        assert moved is not None and moved["stage"] == "loi"

        repository = _repository(database_a, read_a, config)
        with _active(repository, read_a):
            rows_a = await repository.list_deals()
        repository = _repository(database_b, read_b, config)
        with _active(repository, read_b):
            rows_b = await repository.list_deals()

        assert [row["deal_id"] for row in rows_a] == [f"crexi:{shared}"]
        assert [row["deal_id"] for row in rows_b] == [f"crexi:{shared}"]
        assert rows_a[0]["state"] == "CA" and rows_a[0]["stage"] == "lead"
        assert rows_b[0]["state"] == "TX" and rows_b[0]["stage"] == "loi"
    finally:
        database_a.close()
        database_b.close()


@pytest.mark.asyncio
async def test_rows_upgraded_by_0008_remain_readable_and_mutable(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """A deal that predates 0008 must stay usable, not become a visible trap.

    Migration 0008 introduces mandatory source-rights provenance and a listing
    identity contract.  A row created before it has neither, so without an
    upgrade path it would remain listed while every stage and accountability
    write failed forever — and a listing the reader cannot decode would deny
    ``list_deals`` for the entire workspace, healthy deals included.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    from cre_mcp.postgres.migrations import load_migrations

    migrations = load_migrations()
    # Sliced by version rather than by position. These tests exercise the
    # 0008 deal upgrade, and `migrations[:-1]` meant "everything before 0008"
    # only while 0008 happened to be last; adding 0009 silently turned it into
    # "everything including 0008", so the legacy row could no longer be
    # inserted. Naming the version keeps the test about what it is about.
    before_0008 = [item for item in migrations if item.version < 8]
    from_0008 = [item.version for item in migrations if item.version >= 8]
    MigrationRunner(migration_dsn, before_0008).apply()

    actor_id = str(uuid4())
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Legacy Actor','active')",
            (actor_id, f"legacy-{uuid4().hex}@example.test"),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,'ws_deals_a','Legacy Workspace','active')",
            (workspace_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(id,workspace_id,user_id,role,state) "
            "VALUES (%s,%s,%s,'owner','active')",
            (str(uuid4()), workspace_id, actor_id),
        )
        # The default '{}' listing is what 0001 stores when only a title is known.
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "workspace_id,source,source_record_id,title,owner_user_id) "
            "VALUES (%s,'crexi','legacy-empty','Legacy Empty Listing',%s)",
            (workspace_id, actor_id),
        )

    assert MigrationRunner(migration_dsn, migrations).apply() == from_0008

    stage = _admission("update_deal_stage", actor_user_id=actor_id)
    assign = _admission("assign_deal", actor_user_id=actor_id)
    save = _admission("save_deal", actor_user_id=actor_id)
    read = _admission("list_deals", actor_user_id=actor_id)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        for admission in (stage, assign, save, read):
            connection.execute(
                "INSERT INTO medawarcre.access_decision_audit("
                "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
                "session_correlation_hash,request_correlation_id,tool_name,decision,"
                "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
                "%s,'admission',true,%s,%s,"
                "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
                "'authority_admitted','request admitted by live authority',"
                "decode(repeat('41',32),'hex'),decode(repeat('42',32),'hex'))",
                (
                    admission.invocation_id, workspace_id, admission.actor_user_id,
                    admission.session_id, admission.request_correlation_id,
                    admission.tool_name,
                ),
            )

    database = _database(app_dsn)
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(_listing("healthy"))

        # One undecodable legacy row must not deny the whole workspace.
        repository = _repository(database, read, config)
        with _active(repository, read):
            rows = await repository.list_deals()
        assert {row["deal_id"] for row in rows} == {
            "crexi:legacy-empty", "crexi:healthy",
        }

        repository = _repository(database, stage, config)
        with _active(repository, stage):
            moved = await repository.update_stage_result("crexi:legacy-empty", "loi")
        assert moved is not None and moved["stage"] == "loi"

        repository = _repository(database, assign, config)
        with _active(repository, assign):
            owned = await repository.assign_deal(
                "crexi:legacy-empty", owner="Dana", next_action="Call broker"
            )
        assert owned is not None and owned["owner"] == "Dana"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_customer_reachable_reads_have_postgresql_parity(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Parity for the reads shipped capabilities reach but nothing exercised."""
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    assign = _admission("assign_deal", actor_user_id=actor_id)
    unassigned = _admission("unassigned_deals", actor_user_id=actor_id)
    add = _admission("add_investor", actor_user_id=actor_id)
    listing = _admission("list_investors", actor_user_id=actor_id)
    start = _admission("start_exchange", actor_user_id=actor_id)
    status = _admission("exchange_status", actor_user_id=actor_id)
    _, _, database = _seed(
        postgres_database,
        (save, assign, unassigned, add, listing, start, status),
    )
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            accounted = await repository.save_deal(_listing("accounted"))
            await repository.save_deal(_listing("unaccounted"))

        repository = _repository(database, assign, config)
        with _active(repository, assign):
            await repository.assign_deal(
                accounted,
                owner="Dana",
                next_action="Call broker",
                next_action_due="2026-09-01",
            )

        repository = _repository(database, unassigned, config)
        with _active(repository, unassigned):
            gaps = await repository.unaccounted_deals()
        assert [row["deal_id"] for row in gaps] == ["crexi:unaccounted"]
        assert set(gaps[0]["missing"]) == {"owner", "next_action", "next_action_due"}

        repository = _repository(database, add, config)
        with _active(repository, add):
            investor_id = await repository.add_investor(
                "Parity Capital", accredited=True, relationship="preexisting"
            )

        repository = _repository(database, listing, config)
        with _active(repository, listing):
            investors = await repository.list_investors()
        assert [row["investor_id"] for row in investors] == [investor_id]
        assert investors[0]["total_commitments"] == 0

        repository = _repository(database, start, config)
        with _active(repository, start):
            exchange = await repository.create_exchange_result(
                accounted, "2026-01-01", "2026-02-15", "2026-06-30"
            )
        assert exchange is not None

        repository = _repository(database, status, config)
        with _active(repository, status):
            reopened = await repository.get_exchange_record(exchange["exchange_id"])
            missing = await repository.get_exchange_record(str(uuid4()))
        assert reopened is not None
        assert reopened["exchange_id"] == exchange["exchange_id"]
        assert reopened["relinquished_deal_id"] == accounted
        assert reopened["replacements"] == []
        assert missing is None
    finally:
        database.close()


@pytest.mark.asyncio
async def test_frozen_prediction_survives_a_later_rescore(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Re-recording after the deal is rescored must not move the frozen snapshot."""
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    record = _admission("record_deal_outcome", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, record))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            deal_id = await repository.save_deal(
                _listing("frozen"), score=88, grade="A", strategy="core-plus"
            )

        repository = _repository(database, record, config)
        with _active(repository, record):
            first = await repository.record_outcome_result(
                deal_id, {"closed": True, "purchase_price": 2_400_000}
            )
        assert first is not None
        assert (first["predicted_score"], first["predicted_grade"]) == (88.0, "A")

        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(
                _listing("frozen"), score=12, grade="F", strategy="opportunistic"
            )

        repository = _repository(database, record, config)
        with _active(repository, record):
            second = await repository.record_outcome_result(
                deal_id, {"closed": True, "purchase_price": 2_000_000}
            )
        assert second is not None
        assert second["predicted_score"] == 88.0
        assert second["predicted_grade"] == "A"
        assert second["predicted_strategy"] == "core-plus"
        assert second["purchase_price"] == 2_000_000
    finally:
        database.close()


@pytest.mark.asyncio
async def test_plan_replacement_retains_status_and_removes_stale_rows(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Re-planning keeps recorded progress and drops only what left the plan."""
    actor_id = str(uuid4())
    plan = _admission("due_diligence_plan", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (plan,))
    config = _rights_config(tmp_path)

    def _item(key: str, deadline: str) -> DDItem:
        return DDItem(
            key=key,
            label=f"Item {key}",
            why="Confirm ownership",
            what_clears_it="Counsel approval",
            what_should_make_you_terminate="Uncured defect",
            who_to_hire="CRE counsel",
            due_offset_days=5,
            deadline=date.fromisoformat(deadline),
        )

    try:
        repository = _repository(database, plan, config)
        with _active(repository, plan):
            await repository.replace_diligence(
                _listing("replan"),
                [_item("a", "2026-03-01"), _item("b", "2026-03-02"), _item("c", "2026-03-03")],
            )

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.deal_dd_items SET status='complete' "
                "WHERE workspace_id=%s AND item_key='a'",
                (workspace_id,),
            )

        repository = _repository(database, plan, config)
        with _active(repository, plan):
            replanned = await repository.replace_diligence(
                _listing("replan"),
                [_item("a", "2026-04-01"), _item("d", "2026-04-02")],
            )

        stored = {row["key"]: row for row in replanned["items"]}
        assert set(stored) == {"a", "d"}
        assert stored["a"]["status"] == "complete"
        assert stored["a"]["deadline"] == "2026-04-01"
        assert stored["d"]["status"] == "not_started"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_in_flight_revocation_rolls_back_before_commit(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authority lost mid-request must discard the work, not commit it."""
    from cre_mcp.postgres import deals as deals_module

    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    stage = _admission("update_deal_stage", actor_user_id=actor_id)
    read = _admission("list_deals", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, stage, read))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(_listing("revoked-midflight"))

        repository = _repository(database, stage, config)
        real = deals_module.current_hosted_request_repositories
        calls = {"n": 0}

        def _revoke_after_dml():
            calls["n"] += 1
            # Survive entry and the in-transaction dispatch, then vanish exactly
            # where the pre-commit recheck runs.
            return None if calls["n"] > 2 else real()

        with _active(repository, stage):
            monkeypatch.setattr(
                deals_module, "current_hosted_request_repositories", _revoke_after_dml
            )
            with pytest.raises(DealPersistenceUnavailable):
                await repository.update_stage_result("crexi:revoked-midflight", "loi")
            monkeypatch.setattr(
                deals_module, "current_hosted_request_repositories", real
            )

        repository = _repository(database, read, config)
        with _active(repository, read):
            rows = await repository.list_deals()
        assert [row["stage"] for row in rows] == ["lead"]
    finally:
        database.close()


@pytest.mark.asyncio
async def test_multi_statement_reads_use_one_coherent_snapshot(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reads get REPEATABLE READ; lock-and-mutate writes must not.

    The contract promises a multi-statement read returns one transaction
    snapshot. Promoting the write paths too would convert their ``FOR UPDATE``
    wait into a serialization failure, so the isolation choice is pinned on
    both sides here.
    """
    actor_id = str(uuid4())
    read = _admission("list_deals", actor_user_id=actor_id)
    write = _admission("save_deal", actor_user_id=actor_id)
    timeline = _admission("deal_timeline", actor_user_id=actor_id)
    investors = _admission("list_investors", actor_user_id=actor_id)
    exchange = _admission("exchange_status", actor_user_id=actor_id)
    _, _, database = _seed(
        postgres_database, (read, write, timeline, investors, exchange)
    )
    config = _rights_config(tmp_path)
    try:
        with database.admitted_connection(read, snapshot=True) as connection:
            level, read_only = connection.execute(
                "SELECT current_setting('transaction_isolation'),"
                "current_setting('transaction_read_only')"
            ).fetchone()
        assert level == "repeatable read"
        assert read_only == "on"

        with database.admitted_connection(write) as connection:
            level = connection.execute(
                "SELECT current_setting('transaction_isolation')"
            ).fetchone()[0]
        assert level == "read committed"

        # Pin the actual call sites, not just the pool option: dropping
        # `snapshot=True` from a multi-statement read must fail here.
        observed: list[tuple[str, bool]] = []
        original = type(database).admitted_connection

        @contextmanager
        def _record(self, admission, *, snapshot: bool = False):
            observed.append((admission.tool_name, snapshot))
            with original(self, admission, snapshot=snapshot) as connection:
                yield connection

        monkeypatch.setattr(type(database), "admitted_connection", _record)
        for admission, call in (
            (write, lambda r: r.save_deal(_listing("isolation"))),
            (read, lambda r: r.list_deals()),
            (timeline, lambda r: r.get_deal_timeline("crexi:isolation")),
            (investors, lambda r: r.list_investors()),
            (exchange, lambda r: r.get_exchange_record(str(uuid4()))),
        ):
            repository = _repository(database, admission, config)
            with _active(repository, admission):
                await call(repository)

        assert dict(observed) == {
            "save_deal": False,
            "list_deals": True,
            "deal_timeline": True,
            "list_investors": True,
            "exchange_status": True,
        }
    finally:
        database.close()


@pytest.mark.asyncio
async def test_territory_bound_tools_resolve_location_through_the_hosted_port(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Every capability granted `get_deal` must receive a usable projection.

    `_get_deal` projects by exact tool name, so granting a capability method
    authority is not enough — it must also appear in a projection branch. A
    capability bound to a result territory contract that receives no listing
    cannot build its `SubjectProperty` and is denied on every call, including
    for in-territory deals in its own workspace. Local-store fakes hide this
    because they always return a full listing, so this drives the real port.
    """
    from cre_mcp.tools.truth_tools import list_deal_documents

    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    documents = _admission("list_deal_documents", actor_user_id=actor_id)
    timeline = _admission("deal_timeline", actor_user_id=actor_id)
    bridge = _admission("build_noi_bridge", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, documents, timeline, bridge))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            deal_id = await repository.save_deal(_listing("projected"))

        expected = {
            "address": "100 Main Street",
            "city": "Los Angeles",
            "state": "CA",
            "zip_code": "90001",
        }
        for admission in (documents, timeline, bridge):
            repository = _repository(database, admission, config)
            with _active(repository, admission):
                deal = await repository.get_deal(deal_id)
            assert deal is not None, admission.tool_name
            listing = deal.get("listing")
            assert isinstance(listing, dict), (
                f"{admission.tool_name} received no listing projection"
            )
            for key, value in expected.items():
                assert listing.get(key) == value, (admission.tool_name, key)

        # The territory-limited caller must get a real answer, not a denial,
        # for an in-territory deal in its own workspace.
        jv = _context(documents).model_copy(
            update={"profile": Profile.JV_PARTNER, "territories": ("CA",)}
        )

        class _TruthPort:
            async def list_documents(self, _deal_id: str) -> list[dict[str, object]]:
                return []

        repository = _repository(database, documents, config)
        bound = _repositories(documents, repository)
        bound = HostedRequestRepositories(
            admission=documents,
            platform=bound.platform,
            provider=bound.provider,
            search=bound.search,
            deal=repository,
            privacy=bound.privacy,
            job=bound.job,
            document=bound.document,
            truth_asset=_TruthPort(),
        )
        with use_context(jv), use_hosted_request_repositories(bound):
            listed = await list_deal_documents(deal_id)
        assert "error" not in listed, listed
        assert listed["deal_id"] == deal_id
        assert listed["document_count"] == 0
        assert listed["property"] == expected
    finally:
        database.close()


@pytest.mark.asyncio
async def test_a_long_listing_cannot_deny_the_restricted_deal_list(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """A listing this repository accepted must stay listable for JV callers.

    The territory-limited summary path projects a subset of the stored listing.
    Bounding that projection tighter than the write path would let one accepted
    deal deny `list_deals` for the whole workspace, hiding the caller's
    in-territory deals along with it.
    """
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    read = _admission("list_deals", actor_user_id=actor_id)
    _, _, database = _seed(postgres_database, (save, read))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            await repository.save_deal(_listing("compact"))
            verbose = _listing("verbose").model_copy(update={"name": "N" * 40_000})
            await repository.save_deal(verbose)

        jv = _context(read).model_copy(
            update={"profile": Profile.JV_PARTNER, "territories": ("CA",)}
        )
        repository = _repository(database, read, config)
        with use_context(jv), use_hosted_request_repositories(
            _repositories(read, repository)
        ):
            rows = await repository.list_deals()
        assert {row["deal_id"] for row in rows} == {
            "crexi:compact", "crexi:verbose",
        }
    finally:
        database.close()


@pytest.mark.asyncio
async def test_listing_derived_numerics_cannot_overflow_their_columns(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Provider-supplied prices must never hard-fail a hosted write.

    `asking_price` and an exchange replacement `value` are both
    ``numeric(19,2)``, so a listing price at or above 1e17 overflows the column.
    Source parsers return unbounded floats from provider text and the local
    store accepts them, so these write-only columns must be bounded to their
    domain the same way `title` is truncated to its own.
    """
    actor_id = str(uuid4())
    save = _admission("save_deal", actor_user_id=actor_id)
    read = _admission("list_deals", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (save, read))
    config = _rights_config(tmp_path)
    try:
        repository = _repository(database, save, config)
        with _active(repository, save):
            huge = _listing("huge-price").model_copy(
                update={"price_usd": 1e18, "price": "$1,000,000,000,000,000,000"}
            )
            saved = await repository.save_deal(huge)
        assert saved == "crexi:huge-price"

        with psycopg.connect(admin_dsn) as connection:
            stored = connection.execute(
                "SELECT asking_price FROM medawarcre.deals "
                "WHERE workspace_id=%s AND source_record_id='huge-price'",
                (workspace_id,),
            ).fetchone()[0]
        assert stored is None

        repository = _repository(database, read, config)
        with _active(repository, read):
            rows = await repository.list_deals()
        # The authoritative figure still round-trips through the listing JSON.
        assert [row["price_usd"] for row in rows] == [1e18]
    finally:
        database.close()


@pytest.mark.asyncio
async def test_assign_deal_alone_heals_a_pre_0008_row(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """Accountability must heal legacy provenance without a prior stage write.

    `update_stage_result` also heals, so a test that stages first cannot prove
    `assign_deal` does its own healing.  This makes accountability the first
    mutating write the legacy row ever receives.
    """
    admin_dsn, migration_dsn, app_dsn = postgres_database
    from cre_mcp.postgres.migrations import load_migrations

    migrations = load_migrations()
    # Sliced by version rather than by position. These tests exercise the
    # 0008 deal upgrade, and `migrations[:-1]` meant "everything before 0008"
    # only while 0008 happened to be last; adding 0009 silently turned it into
    # "everything including 0008", so the legacy row could no longer be
    # inserted. Naming the version keeps the test about what it is about.
    before_0008 = [item for item in migrations if item.version < 8]
    from_0008 = [item.version for item in migrations if item.version >= 8]
    MigrationRunner(migration_dsn, before_0008).apply()
    actor_id = str(uuid4())
    workspace_id = str(uuid4())
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.users(id,email,name,state) "
            "VALUES (%s,%s,'Legacy Actor','active')",
            (actor_id, f"legacy-{uuid4().hex}@example.test"),
        )
        connection.execute(
            "INSERT INTO medawarcre.workspaces(id,public_id,name,state) "
            "VALUES (%s,'ws_deals_a','Legacy Workspace','active')",
            (workspace_id,),
        )
        connection.execute(
            "INSERT INTO medawarcre.memberships(id,workspace_id,user_id,role,state) "
            "VALUES (%s,%s,%s,'owner','active')",
            (str(uuid4()), workspace_id, actor_id),
        )
        connection.execute(
            "INSERT INTO medawarcre.deals("
            "workspace_id,source,source_record_id,title,owner_user_id) "
            "VALUES (%s,'crexi','legacy-assign','Legacy Assign',%s)",
            (workspace_id, actor_id),
        )
    assert MigrationRunner(migration_dsn, migrations).apply() == from_0008

    assign = _admission("assign_deal", actor_user_id=actor_id)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET ROLE medawarcre_migration")
        connection.execute(
            "INSERT INTO medawarcre.access_decision_audit("
            "invocation_id,phase,authenticated,workspace_id,actor_user_id,"
            "session_correlation_hash,request_correlation_id,tool_name,decision,"
            "reason_code,safe_reason,args_hash,admission_binding_hash) VALUES ("
            "%s,'admission',true,%s,%s,"
            "pg_catalog.sha256(pg_catalog.convert_to(%s,'UTF8')),%s,%s,'allowed',"
            "'authority_admitted','request admitted by live authority',"
            "decode(repeat('41',32),'hex'),decode(repeat('42',32),'hex'))",
            (
                assign.invocation_id, workspace_id, assign.actor_user_id,
                assign.session_id, assign.request_correlation_id, assign.tool_name,
            ),
        )

    database = _database(app_dsn)
    try:
        repository = _repository(database, assign, _rights_config(tmp_path))
        with _active(repository, assign):
            owned = await repository.assign_deal(
                "crexi:legacy-assign", owner="Dana", next_action="Call broker"
            )
        assert owned is not None and owned["owner"] == "Dana"
    finally:
        database.close()


@pytest.mark.asyncio
async def test_operating_replan_removes_stale_events_and_keeps_status(
    postgres_database: tuple[str, str, str],
    tmp_path: Path,
) -> None:
    """The operating calendar gets the same replacement proof as diligence."""
    actor_id = str(uuid4())
    playbook = _admission("operating_playbook", actor_user_id=actor_id)
    admin_dsn, workspace_id, database = _seed(postgres_database, (playbook,))
    config = _rights_config(tmp_path)

    def _event(key: str, day: str) -> dict[str, object]:
        return {
            "key": key,
            "label": f"Event {key}",
            "category": "recurring",
            "event_date": day,
            "status": "not_started",
        }

    try:
        repository = _repository(database, playbook, config)
        with _active(repository, playbook):
            await repository.replace_operating(
                _listing("ops-replan"),
                [_event("a", "2026-03-01"), _event("b", "2026-03-02"), _event("c", "2026-03-03")],
            )

        with psycopg.connect(admin_dsn) as connection:
            connection.execute("SET ROLE medawarcre_migration")
            connection.execute(
                "UPDATE medawarcre.deal_ops_events SET status='complete' "
                "WHERE workspace_id=%s AND event_key='a'",
                (workspace_id,),
            )

        repository = _repository(database, playbook, config)
        with _active(repository, playbook):
            await repository.replace_operating(
                _listing("ops-replan"),
                [_event("a", "2026-04-01"), _event("d", "2026-04-02")],
            )

        with psycopg.connect(admin_dsn) as connection:
            rows = dict(
                connection.execute(
                    "SELECT event_key,status FROM medawarcre.deal_ops_events "
                    "WHERE workspace_id=%s ORDER BY event_key",
                    (workspace_id,),
                ).fetchall()
            )
        assert set(rows) == {"a", "d"}
        assert rows["a"] == "complete"
        assert rows["d"] == "not_started"
    finally:
        database.close()
