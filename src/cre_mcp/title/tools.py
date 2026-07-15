"""Unregistered, explicit-signature title screening functions.

These are deliberately ordinary Python functions.  They are not registered as
FastMCP tools here, and they do not accept arbitrary keyword arguments.
"""

from __future__ import annotations

from typing import Any

from cre_mcp.title.commitment import parse_title_commitment as _parse_title_commitment
from cre_mcp.title.easements import assess_recorded_burdens as _assess_recorded_burdens
from cre_mcp.title.issue_list import attorney_issue_list as _attorney_issue_list
from cre_mcp.title.legal_compare import (
    compare_legal_descriptions as _compare_legal_descriptions,
)
from cre_mcp.title.liens import screen_encumbrances as _screen_encumbrances
from cre_mcp.title.survey_review import survey_vs_title as _survey_vs_title


def parse_title_commitment(text: str) -> dict[str, Any]:
    """Return a cited, non-legal title-commitment issue screen."""
    return _parse_title_commitment(text)


def screen_encumbrances(
    records: list[dict[str, Any]],
    closing_context: dict[str, Any],
) -> dict[str, Any]:
    """Screen recorded encumbrance inputs for closing-resolution issues."""
    return _screen_encumbrances(records, closing_context)


def compare_legal_descriptions(
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare supplied legal-description representations without choosing one."""
    return _compare_legal_descriptions(sources)


def assess_recorded_burdens(
    items: list[dict[str, Any]],
    intended_use: str | None,
) -> dict[str, Any]:
    """Frame cited recorded burdens for title-company and counsel review."""
    return _assess_recorded_burdens(items, intended_use)


def survey_vs_title(
    survey_items: list[dict[str, Any]],
    title_exceptions: list[dict[str, Any]],
    site_plan_intent: str | None = None,
) -> dict[str, Any]:
    """Reconcile survey annotations with title exceptions as an issue screen."""
    return _survey_vs_title(survey_items, title_exceptions, site_plan_intent)


def attorney_issue_list(
    deal_id: str | None = None,
    title_commitment: dict[str, Any] | None = None,
    encumbrances: dict[str, Any] | None = None,
    legal_comparison: dict[str, Any] | None = None,
    recorded_burdens: dict[str, Any] | None = None,
    survey_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidate module outputs into a deduplicated routed issue list."""
    return _attorney_issue_list(
        deal_id,
        title_commitment,
        encumbrances,
        legal_comparison,
        recorded_burdens,
        survey_review,
    )


__all__ = [
    "parse_title_commitment",
    "screen_encumbrances",
    "compare_legal_descriptions",
    "assess_recorded_burdens",
    "survey_vs_title",
    "attorney_issue_list",
]
