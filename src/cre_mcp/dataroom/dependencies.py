"""Transaction dependency graph, deadline blockers, and closing runway."""

from __future__ import annotations

import heapq
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

from cre_mcp.config import CreConfig
from cre_mcp.deals.store import DealStore

from .taxonomy import DEAL_TYPES

TASK_STATUSES = frozenset({"not_started", "in_progress", "blocked", "complete", "waived"})
DONE_STATUSES = frozenset({"complete", "waived"})
DEPENDENCY_CONVENTION = (
    "Template edges are CRE planning conventions, not inferred contractual facts; "
    "confirm every lender, PSA, title, survey, tenant, and escrow requirement."
)
SLACK_CONVENTION = (
    "slack_days is calendar days from as_of through the task deadline (negative is overdue); "
    "it is not CPM float because the table has deadlines but no task-duration estimates."
)
CLOSING_RUNWAY_CONVENTION = (
    "The closing runway includes tasks dated from closing_date minus 7 calendar days "
    "through closing_date, plus any incomplete prerequisites that block those tasks."
)


class DependencyTemplateItem(TypedDict):
    task_key: str
    label: str
    depends_on: tuple[str, ...]
    days_before_closing: int
    owner: str | None
    critical: bool


def _task(
    task_key: str,
    label: str,
    days_before_closing: int,
    *,
    depends_on: tuple[str, ...] = (),
    owner: str | None,
    critical: bool = False,
) -> DependencyTemplateItem:
    return {
        "task_key": task_key,
        "label": label,
        "depends_on": depends_on,
        "days_before_closing": days_before_closing,
        "owner": owner,
        "critical": critical,
    }


def _income_template(
    special_key: str,
    special_label: str,
    *,
    estoppel_label: str = "Collect required tenant estoppels",
) -> tuple[DependencyTemplateItem, ...]:
    return (
        _task(
            "property_access", "Secure third-party property access", 42,
            owner="acquisitions", critical=True,
        ),
        _task(
            "order_title", "Order title commitment and exceptions", 42,
            owner="title_counsel", critical=True,
        ),
        _task(
            "lease_review", "Complete lease and amendment review", 32,
            owner="real_estate_counsel", critical=True,
        ),
        _task(
            special_key, special_label, 28,
            depends_on=("lease_review",), owner="acquisitions",
        ),
        _task(
            "order_survey", "Complete ALTA survey fieldwork", 30,
            depends_on=("property_access",), owner="surveyor", critical=True,
        ),
        _task(
            "phase_i", "Complete Phase I environmental review", 30,
            depends_on=("property_access",), owner="environmental_consultant", critical=True,
        ),
        _task(
            "pca", "Complete property condition assessment", 28,
            depends_on=("property_access",), owner="engineer",
        ),
        _task(
            "appraisal", "Complete lender appraisal", 21,
            depends_on=("property_access",), owner="lender", critical=True,
        ),
        _task(
            "review_title", "Review title and exception documents", 28,
            depends_on=("order_title",), owner="title_counsel", critical=True,
        ),
        _task(
            "review_survey", "Reconcile survey to title", 20,
            depends_on=("order_survey", "review_title"), owner="title_counsel", critical=True,
        ),
        _task(
            "title_cure", "Resolve title and survey objections", 10,
            depends_on=("review_title", "review_survey"), owner="title_counsel", critical=True,
        ),
        _task(
            "request_estoppels", "Send approved estoppel forms", 27,
            depends_on=("lease_review",), owner="seller", critical=True,
        ),
        _task(
            "receive_estoppels", estoppel_label, 10,
            depends_on=("request_estoppels",), owner="seller", critical=True,
        ),
        _task(
            "environmental_clearance", "Clear environmental conditions", 14,
            depends_on=("phase_i",), owner="environmental_consultant", critical=True,
        ),
        _task(
            "insurance_binder", "Bind lender-compliant insurance", 7,
            depends_on=("pca", "environmental_clearance"), owner="insurance_broker", critical=True,
        ),
        _task(
            "financing_approval", "Clear final loan approval", 5,
            depends_on=(
                "appraisal", "receive_estoppels", "title_cure",
                "insurance_binder", special_key,
            ),
            owner="lender", critical=True,
        ),
        _task(
            "settlement_statement", "Approve settlement statement and prorations", 2,
            depends_on=("title_cure",), owner="acquisitions", critical=True,
        ),
        _task(
            "closing_documents", "Approve and execute closing documents", 2,
            depends_on=("financing_approval", "title_cure", "environmental_clearance"),
            owner="real_estate_counsel", critical=True,
        ),
        _task(
            "final_walkthrough", "Complete final walkthrough", 1,
            depends_on=("property_access",), owner="acquisitions", critical=True,
        ),
        _task(
            "funds_ready", "Verify equity and lender funds ready", 1,
            depends_on=("financing_approval", "settlement_statement"),
            owner="treasury", critical=True,
        ),
        _task(
            "close_funding", "Authorize escrow funding and release", 0,
            depends_on=("closing_documents", "final_walkthrough", "funds_ready"),
            owner="acquisitions", critical=True,
        ),
        _task(
            "record_deed", "Confirm deed recorded and title funded", 0,
            depends_on=("close_funding",), owner="escrow", critical=True,
        ),
    )


LAND_TEMPLATE: tuple[DependencyTemplateItem, ...] = (
    _task(
        "property_access", "Secure consultant and survey access", 55,
        owner="acquisitions", critical=True,
    ),
    _task(
        "order_title", "Order title commitment and exceptions", 55,
        owner="title_counsel", critical=True,
    ),
    _task(
        "concept_plan", "Complete concept plan and yield study", 42,
        depends_on=("property_access",), owner="civil_engineer", critical=True,
    ),
    _task(
        "order_survey", "Complete ALTA and topographic survey", 40,
        depends_on=("property_access",), owner="surveyor", critical=True,
    ),
    _task(
        "phase_i", "Complete Phase I environmental review", 40,
        depends_on=("property_access",), owner="environmental_consultant", critical=True,
    ),
    _task(
        "geotechnical_review", "Complete geotechnical investigation", 35,
        depends_on=("property_access",), owner="geotechnical_engineer", critical=True,
    ),
    _task(
        "utility_capacity", "Confirm utility capacity and will-serve path", 30,
        depends_on=("concept_plan",), owner="civil_engineer", critical=True,
    ),
    _task(
        "land_use_review", "Confirm zoning and entitlement path", 35,
        depends_on=("concept_plan",), owner="land_use_counsel", critical=True,
    ),
    _task(
        "review_title", "Review title and exception documents", 38,
        depends_on=("order_title",), owner="title_counsel", critical=True,
    ),
    _task(
        "review_survey", "Reconcile survey, access, and title", 28,
        depends_on=("order_survey", "review_title"), owner="title_counsel", critical=True,
    ),
    _task(
        "title_cure", "Resolve title, access, and survey objections", 12,
        depends_on=("review_title", "review_survey"), owner="title_counsel", critical=True,
    ),
    _task(
        "environmental_clearance", "Clear environmental and site constraints", 20,
        depends_on=("phase_i", "geotechnical_review"),
        owner="environmental_consultant", critical=True,
    ),
    _task(
        "appraisal", "Complete lender appraisal", 21,
        depends_on=("property_access", "concept_plan"), owner="lender", critical=True,
    ),
    _task(
        "financing_approval", "Clear final acquisition-loan approval", 6,
        depends_on=(
            "appraisal", "title_cure", "environmental_clearance",
            "utility_capacity", "land_use_review",
        ),
        owner="lender", critical=True,
    ),
    _task(
        "settlement_statement", "Approve settlement statement", 2,
        depends_on=("title_cure",), owner="acquisitions", critical=True,
    ),
    _task(
        "closing_documents", "Approve and execute closing documents", 2,
        depends_on=("financing_approval", "title_cure"),
        owner="real_estate_counsel", critical=True,
    ),
    _task(
        "final_site_walk", "Complete final site and access walk", 1,
        depends_on=("property_access",), owner="acquisitions", critical=True,
    ),
    _task(
        "funds_ready", "Verify equity and lender funds ready", 1,
        depends_on=("financing_approval", "settlement_statement"),
        owner="treasury", critical=True,
    ),
    _task(
        "close_funding", "Authorize escrow funding and release", 0,
        depends_on=("closing_documents", "final_site_walk", "funds_ready"),
        owner="acquisitions", critical=True,
    ),
    _task(
        "record_deed", "Confirm deed recorded and title funded", 0,
        depends_on=("close_funding",), owner="escrow", critical=True,
    ),
)


STANDARD_DEPENDENCY_TEMPLATES: dict[str, tuple[DependencyTemplateItem, ...]] = {
    "retail_nnn": _income_template(
        "tenant_credit_review", "Approve tenant and guarantor credit review"
    ),
    "multifamily": _income_template(
        "unit_file_review",
        "Complete unit-file, deposit, and delinquency review",
        estoppel_label="Complete required resident confirmation or estoppel sample",
    ),
    "office": _income_template(
        "leasing_cost_review", "Approve TI, LC, and free-rent obligation schedule"
    ),
    "industrial": _income_template(
        "industrial_use_review", "Clear tenant-use and environmental compliance review"
    ),
    "land": LAND_TEMPLATE,
}


def _as_date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} cannot be blank")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DependencyStore:
    """Own the isolated transaction-dependency table in the shared cache DB."""

    def __init__(
        self,
        db_path: str | Path | CreConfig | None = None,
        *,
        config: CreConfig | None = None,
    ) -> None:
        self.db_path = DealStore(db_path or config).db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS txn_dependencies (
                deal_id TEXT NOT NULL,
                task_key TEXT NOT NULL,
                label TEXT NOT NULL,
                depends_on TEXT NOT NULL DEFAULT '[]',
                deadline TEXT NOT NULL,
                owner TEXT,
                status TEXT NOT NULL DEFAULT 'not_started',
                critical INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(deal_id, task_key),
                CHECK(status IN ('not_started', 'in_progress', 'blocked', 'complete', 'waived')),
                CHECK(critical IN (0, 1))
            );
            CREATE INDEX IF NOT EXISTS idx_txn_dependencies_deadline
                ON txn_dependencies(deal_id, deadline, task_key);
            """
        )
        return connection

    @staticmethod
    def _deal_id(deal_id: str) -> str:
        normalized = str(deal_id).strip()
        if not normalized:
            raise ValueError("deal_id cannot be blank")
        return normalized

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        dependencies = json.loads(str(row["depends_on"]))
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) for item in dependencies
        ):
            raise ValueError(f"depends_on is not a JSON string list for {row['task_key']}")
        return {
            "deal_id": row["deal_id"],
            "task_key": row["task_key"],
            "label": row["label"],
            "depends_on": dependencies,
            "deadline": row["deadline"],
            "owner": row["owner"],
            "status": row["status"],
            "critical": bool(row["critical"]),
        }

    def init_transaction_plan(
        self,
        deal_id: str,
        deal_type: str,
        closing_date: Any,
    ) -> dict[str, Any]:
        """Upsert a dated planning template while preserving status and reassignment."""

        normalized_id = self._deal_id(deal_id)
        normalized_type = str(deal_type).strip().casefold()
        if normalized_type not in STANDARD_DEPENDENCY_TEMPLATES:
            raise ValueError(f"deal_type must be one of: {', '.join(DEAL_TYPES)}")
        close_date = _as_date(closing_date, "closing_date")
        template = STANDARD_DEPENDENCY_TEMPLATES[normalized_type]
        with self._connect() as connection:
            for item in template:
                deadline = close_date - timedelta(days=item["days_before_closing"])
                connection.execute(
                    """
                    INSERT INTO txn_dependencies(
                        deal_id, task_key, label, depends_on, deadline,
                        owner, status, critical
                    ) VALUES (?, ?, ?, ?, ?, ?, 'not_started', ?)
                    ON CONFLICT(deal_id, task_key) DO UPDATE SET
                        label=excluded.label,
                        depends_on=excluded.depends_on,
                        deadline=excluded.deadline,
                        owner=COALESCE(txn_dependencies.owner, excluded.owner),
                        critical=excluded.critical
                    """,
                    (
                        normalized_id,
                        item["task_key"],
                        item["label"],
                        json.dumps(item["depends_on"], separators=(",", ":")),
                        deadline.isoformat(),
                        item["owner"],
                        int(item["critical"]),
                    ),
                )
            rows = connection.execute(
                """
                SELECT * FROM txn_dependencies WHERE deal_id=?
                ORDER BY deadline, task_key
                """,
                (normalized_id,),
            ).fetchall()
        return {
            "deal_id": normalized_id,
            "deal_type": normalized_type,
            "closing_date": close_date.isoformat(),
            "task_count": len(rows),
            "tasks": [self._decode(row) for row in rows],
            "dependency_inference": "CONVENTION",
            "convention": DEPENDENCY_CONVENTION,
        }

    def upsert_task(
        self,
        deal_id: str,
        task_key: str,
        label: str,
        *,
        depends_on: list[str] | tuple[str, ...] = (),
        deadline: Any,
        owner: str | None = None,
        status: str = "not_started",
        critical: bool = False,
    ) -> dict[str, Any]:
        """Upsert a user-confirmed dependency row (also useful for isolated tests)."""

        normalized_id = self._deal_id(deal_id)
        normalized_key = str(task_key).strip()
        normalized_label = str(label).strip()
        if not normalized_key or not normalized_label:
            raise ValueError("task_key and label are required")
        normalized_status = str(status).strip().casefold()
        if normalized_status not in TASK_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(TASK_STATUSES))}")
        normalized_dependencies: list[str] = []
        for dependency in depends_on:
            normalized_dependency = str(dependency).strip()
            if not normalized_dependency:
                raise ValueError("depends_on cannot contain blank task keys")
            if normalized_dependency not in normalized_dependencies:
                normalized_dependencies.append(normalized_dependency)
        normalized_owner = str(owner).strip() if owner is not None else None
        normalized_owner = normalized_owner or None
        deadline_text = _as_date(deadline, "deadline").isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO txn_dependencies(
                    deal_id, task_key, label, depends_on, deadline,
                    owner, status, critical
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(deal_id, task_key) DO UPDATE SET
                    label=excluded.label,
                    depends_on=excluded.depends_on,
                    deadline=excluded.deadline,
                    owner=excluded.owner,
                    status=excluded.status,
                    critical=excluded.critical
                """,
                (
                    normalized_id,
                    normalized_key,
                    normalized_label,
                    json.dumps(normalized_dependencies, separators=(",", ":")),
                    deadline_text,
                    normalized_owner,
                    normalized_status,
                    int(bool(critical)),
                ),
            )
            row = connection.execute(
                "SELECT * FROM txn_dependencies WHERE deal_id=? AND task_key=?",
                (normalized_id, normalized_key),
            ).fetchone()
        assert row is not None
        return self._decode(row)

    def update_task_status(self, deal_id: str, task_key: str, status: str) -> dict[str, Any]:
        normalized_status = str(status).strip().casefold()
        if normalized_status not in TASK_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(TASK_STATUSES))}")
        normalized_id = self._deal_id(deal_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE txn_dependencies SET status=? WHERE deal_id=? AND task_key=?",
                (normalized_status, normalized_id, str(task_key).strip()),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown transaction task: {normalized_id}/{task_key}")
            row = connection.execute(
                "SELECT * FROM txn_dependencies WHERE deal_id=? AND task_key=?",
                (normalized_id, str(task_key).strip()),
            ).fetchone()
        assert row is not None
        return self._decode(row)

    def _tasks(self, deal_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM txn_dependencies WHERE deal_id=?
                ORDER BY deadline, task_key
                """,
                (deal_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _topological_order(tasks: list[dict[str, Any]]) -> list[str]:
        by_key = {task["task_key"]: task for task in tasks}
        for task in tasks:
            unknown = [key for key in task["depends_on"] if key not in by_key]
            if unknown:
                raise ValueError(
                    f"task {task['task_key']} has unknown dependencies: {', '.join(unknown)}"
                )
        indegree = {key: 0 for key in by_key}
        dependents: dict[str, list[str]] = {key: [] for key in by_key}
        for task in tasks:
            key = task["task_key"]
            indegree[key] = len(task["depends_on"])
            for prerequisite in task["depends_on"]:
                dependents[prerequisite].append(key)
        ready: list[tuple[str, str]] = [
            (str(by_key[key]["deadline"]), key)
            for key, count in indegree.items()
            if count == 0
        ]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            _, key = heapq.heappop(ready)
            order.append(key)
            for dependent in sorted(dependents[key]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(
                        ready,
                        (str(by_key[dependent]["deadline"]), dependent),
                    )
        if len(order) != len(tasks):
            cyclic = sorted(key for key, count in indegree.items() if count > 0)
            raise ValueError(
                "transaction dependency cycle detected involving: " + ", ".join(cyclic)
            )
        return order

    @staticmethod
    def _longest_critical_path(
        order: list[str], by_key: dict[str, dict[str, Any]]
    ) -> list[str]:
        paths: dict[str, list[str]] = {}
        for key in order:
            dependencies = by_key[key]["depends_on"]
            if not dependencies:
                paths[key] = [key]
                continue
            best = max(
                (paths[dependency] for dependency in dependencies),
                key=lambda path: (len(path), tuple(path)),
            )
            paths[key] = [*best, key]
        critical_endpoints = [key for key in order if by_key[key]["critical"]]
        if not critical_endpoints:
            return []
        return max(
            (paths[key] for key in critical_endpoints),
            key=lambda path: (len(path), tuple(path)),
        )

    def critical_path(self, deal_id: str, *, as_of: Any = None) -> dict[str, Any]:
        """Return graph order, deadline blockers, slack, and conventional SPOFs."""

        normalized_id = self._deal_id(deal_id)
        as_of_date = _as_date(as_of or datetime.now(UTC), "as_of")
        tasks = self._tasks(normalized_id)
        if not tasks:
            return {
                "deal_id": normalized_id,
                "initialized": False,
                "as_of": as_of_date.isoformat(),
                "topological_order": [],
                "critical_path": [],
                "current_blockers": [],
                "slack": [],
                "single_points_of_failure": [],
                "note": "No transaction dependency plan has been initialized for this deal.",
                "dependency_inference": "CONVENTION",
                "convention": DEPENDENCY_CONVENTION,
            }
        by_key = {task["task_key"]: task for task in tasks}
        order = self._topological_order(tasks)
        path = self._longest_critical_path(order, by_key)
        blockers: list[dict[str, Any]] = []
        for key in order:
            task = by_key[key]
            if task["status"] in DONE_STATUSES:
                continue
            if _as_date(task["deadline"], "deadline") > as_of_date:
                continue
            for prerequisite_key in task["depends_on"]:
                prerequisite = by_key[prerequisite_key]
                if prerequisite["status"] not in DONE_STATUSES:
                    blockers.append(
                        {
                            "blocked_task_key": key,
                            "blocked_task_label": task["label"],
                            "blocked_task_deadline": task["deadline"],
                            "prerequisite_task_key": prerequisite_key,
                            "prerequisite_label": prerequisite["label"],
                            "prerequisite_status": prerequisite["status"],
                            "prerequisite_owner": prerequisite["owner"],
                            "reason": "incomplete prerequisite of a due task",
                        }
                    )
        slack: list[dict[str, Any]] = []
        for key in order:
            task = by_key[key]
            days = (_as_date(task["deadline"], "deadline") - as_of_date).days
            state = "complete" if task["status"] in DONE_STATUSES else (
                "overdue" if days < 0 else "due_today" if days == 0 else "remaining"
            )
            slack.append(
                {
                    "task_key": key,
                    "deadline": task["deadline"],
                    "slack_days": days,
                    "schedule_state": state,
                    "status": task["status"],
                }
            )
        single_points: list[dict[str, Any]] = []
        seen_spofs: set[tuple[str, str, str | None]] = set()
        for key in order:
            task = by_key[key]
            if task["critical"] and task["status"] not in DONE_STATUSES and not task["owner"]:
                marker = (key, "unassigned_critical_task", None)
                if marker not in seen_spofs:
                    seen_spofs.add(marker)
                    single_points.append(
                        {
                            "task_key": key,
                            "label": task["label"],
                            "owner": None,
                            "reason": "unassigned_critical_task",
                            "blocks": [],
                        }
                    )
            if not task["critical"] or task["status"] in DONE_STATUSES:
                continue
            incomplete = [
                dependency
                for dependency in task["depends_on"]
                if by_key[dependency]["status"] not in DONE_STATUSES
            ]
            if len(incomplete) == 1:
                prerequisite_key = incomplete[0]
                prerequisite = by_key[prerequisite_key]
                marker = (prerequisite_key, "sole_incomplete_prerequisite", key)
                if marker not in seen_spofs:
                    seen_spofs.add(marker)
                    single_points.append(
                        {
                            "task_key": prerequisite_key,
                            "label": prerequisite["label"],
                            "owner": prerequisite["owner"],
                            "reason": "sole_incomplete_prerequisite",
                            "blocks": [key],
                        }
                    )
        return {
            "deal_id": normalized_id,
            "initialized": True,
            "as_of": as_of_date.isoformat(),
            "tasks": [by_key[key] for key in order],
            "topological_order": order,
            "critical_tasks": [key for key in order if by_key[key]["critical"]],
            "critical_path": path,
            "critical_path_convention": (
                "Longest prerequisite chain by task count ending at a task marked critical; "
                "duration-free and therefore not a CPM duration forecast."
            ),
            "current_blockers": blockers,
            "slack": slack,
            "slack_convention": SLACK_CONVENTION,
            "single_points_of_failure": single_points,
            "single_point_convention": (
                "Flags unassigned incomplete critical tasks and sole remaining incomplete "
                "prerequisites of an incomplete critical task."
            ),
            "dependency_inference": "CONVENTION",
            "convention": DEPENDENCY_CONVENTION,
        }

    def closing_runway(self, deal_id: str, *, as_of: Any = None) -> dict[str, Any]:
        """Return the last-seven-days slice and its incomplete external prerequisites."""

        normalized_id = self._deal_id(deal_id)
        path_result = self.critical_path(normalized_id, as_of=as_of)
        if not path_result["initialized"]:
            return {
                "deal_id": normalized_id,
                "initialized": False,
                "closing_date": None,
                "window_start": None,
                "tasks": [],
                "blocking_prerequisites": [],
                "note": path_result["note"],
                "convention": CLOSING_RUNWAY_CONVENTION,
            }
        tasks = path_result["tasks"]
        by_key = {task["task_key"]: task for task in tasks}
        closing_date = max(_as_date(task["deadline"], "deadline") for task in tasks)
        window_start = closing_date - timedelta(days=7)
        runway = [
            task
            for task in tasks
            if window_start <= _as_date(task["deadline"], "deadline") <= closing_date
        ]
        runway_keys = {task["task_key"] for task in runway}
        blocking: list[dict[str, Any]] = []
        for task in runway:
            if task["status"] in DONE_STATUSES:
                continue
            for prerequisite_key in task["depends_on"]:
                prerequisite = by_key[prerequisite_key]
                if prerequisite["status"] in DONE_STATUSES:
                    continue
                blocking.append(
                    {
                        "blocked_task_key": task["task_key"],
                        "prerequisite_task_key": prerequisite_key,
                        "prerequisite_label": prerequisite["label"],
                        "prerequisite_status": prerequisite["status"],
                        "prerequisite_owner": prerequisite["owner"],
                        "prerequisite_in_runway": prerequisite_key in runway_keys,
                    }
                )
        return {
            "deal_id": normalized_id,
            "initialized": True,
            "closing_date": closing_date.isoformat(),
            "window_start": window_start.isoformat(),
            "tasks": runway,
            "task_keys": [task["task_key"] for task in runway],
            "blocking_prerequisites": blocking,
            "dependency_inference": "CONVENTION",
            "convention": CLOSING_RUNWAY_CONVENTION,
        }


def critical_path(
    deal_id: str,
    as_of: Any = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Convenience function over :class:`DependencyStore`."""

    return DependencyStore(db_path).critical_path(deal_id, as_of=as_of)


def closing_runway(
    deal_id: str,
    as_of: Any = None,
    *,
    db_path: str | Path | CreConfig | None = None,
) -> dict[str, Any]:
    """Convenience function over :class:`DependencyStore`."""

    return DependencyStore(db_path).closing_runway(deal_id, as_of=as_of)


__all__ = [
    "CLOSING_RUNWAY_CONVENTION",
    "DEPENDENCY_CONVENTION",
    "DependencyStore",
    "SLACK_CONVENTION",
    "STANDARD_DEPENDENCY_TEMPLATES",
    "TASK_STATUSES",
    "closing_runway",
    "critical_path",
]
