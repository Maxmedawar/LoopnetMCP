"""Priority-ordered orchestration for counterparty registry screening."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Sequence
from typing import Any

from cre_mcp.http.fetch import FetchClient
from cre_mcp.verifyreg.finra import (
    UNDOCUMENTED_API_NOTE,
    search_brokercheck_firms,
    search_brokercheck_individuals,
    search_iapd_firms,
    search_iapd_individuals,
)
from cre_mcp.verifyreg.stateboards import (
    search_co_all_professions,
    search_co_real_estate,
    search_tx_tdlr,
    tx_trec_link_out,
)

VALID_ROLES = frozenset(
    {"broker_dealer", "adviser", "real_estate", "contractor", "appraiser", "mlo"}
)
DEFAULT_ROLES = (
    "broker_dealer",
    "adviser",
    "real_estate",
    "contractor",
    "appraiser",
    "mlo",
)

IDENTITY_CAVEAT = (
    "Results are candidate matches only and never assert identity. Same-name "
    "collisions are real; compare CRD/license number, legal name, firm, location, "
    "and other registry-returned fields before relying on a result."
)
NO_MATCH_CAVEAT = (
    "No match found does not mean unlicensed. Coverage is incomplete, and spelling, "
    "former names, suffixes, business aliases, state selection, and source latency "
    "can prevent a match."
)
DISCIPLINE_CAVEAT = (
    "Current license/registration status is not disciplinary history. A credential "
    "can be active after reinstatement; review BrokerCheck disclosures, SEC Form ADV "
    "DRPs, ASC notices, and the relevant state enforcement history."
)


def nmls_deep_link(value: str | int | None, entity_type: str = "INDIVIDUAL") -> str:
    """Build an official NMLS detail link when an ID is present, else the lookup root."""
    if value is None:
        return "https://www.nmlsconsumeraccess.org/"
    match = re.search(r"(?:NMLS(?:\s*(?:ID|#))?\s*)?(\d{4,})", str(value), re.I)
    if not match:
        return "https://www.nmlsconsumeraccess.org/"
    kind = entity_type.strip().upper()
    if kind not in {"INDIVIDUAL", "COMPANY"}:
        raise ValueError("NMLS entity_type must be INDIVIDUAL or COMPANY")
    return (
        "https://www.nmlsconsumeraccess.org/EntityDetails.aspx/"
        f"{kind}/{match.group(1)}"
    )


def _link_out(deep_link: str, note: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "not_queryable",
        "candidates": [],
        "deep_link": deep_link,
        "note": note,
        **extra,
    }


async def _source_result(
    query: Awaitable[list[dict[str, Any]]], *, fragility_note: str | None = None
) -> dict[str, Any]:
    try:
        candidates = await query
    except Exception as exc:
        result: dict[str, Any] = {
            "status": "error",
            "candidates": [],
            "note": f"Source failed closed; this is not a no-match result. {exc}",
        }
    else:
        result = {
            "status": "candidate_matches" if candidates else "no_match",
            "candidates": candidates,
        }
        if not candidates:
            result["note"] = NO_MATCH_CAVEAT
    if fragility_note:
        result["fragility_note"] = fragility_note
    return result


def _disciplinary_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    flags: list[dict[str, Any]] = []
    active_statuses = {"active", "current", "current, active", "probation, active"}
    for source_name, result in sources.items():
        for candidate in result.get("candidates", []):
            if source_name.startswith("finra_brokercheck"):
                count = candidate.get("disclosure_count")
                disclosure_flag = str(candidate.get("disclosure_flag", "")).upper()
                if isinstance(count, int) and count > 0:
                    flags.append(
                        {
                            "source": source_name,
                            "candidate": candidate.get("crd"),
                            "kind": "brokercheck_disclosures",
                            "disclosure_count": count,
                        }
                    )
                elif disclosure_flag == "Y":
                    flags.append(
                        {
                            "source": source_name,
                            "candidate": candidate.get("crd"),
                            "kind": "brokercheck_disclosures",
                            "disclosure_count": None,
                            "note": (
                                "BrokerCheck search flags one or more disclosures but "
                                "did not return an exact count; open the profile history."
                            ),
                        }
                    )
            status = candidate.get("status")
            if status not in (None, "") and str(status).strip().lower() not in active_statuses:
                flags.append(
                    {
                        "source": source_name,
                        "candidate": candidate.get("license_no") or candidate.get("crd"),
                        "kind": "current_status_flag",
                        "status": status,
                    }
                )
    return {"flags": flags, "note": DISCIPLINE_CAVEAT}


async def verify_counterparty(
    name: str,
    state: str | None = None,
    roles: Sequence[str] | None = None,
    *,
    client: FetchClient | None = None,
) -> dict[str, Any]:
    """Screen a name across applicable primary sources in §10 priority order."""
    if not name or not name.strip():
        raise ValueError("Counterparty name is required")
    selected = tuple(roles) if roles is not None else DEFAULT_ROLES
    unknown = set(selected) - VALID_ROLES
    if unknown:
        raise ValueError(f"Unsupported role(s): {', '.join(sorted(unknown))}")
    normalized_state = state.strip().upper() if state else None

    # Entries are collected in the specification's priority order, while API calls
    # themselves run concurrently. Values are either awaitables or ready link-outs.
    entries: list[tuple[str, Awaitable[dict[str, Any]] | dict[str, Any]]] = []

    # 1. FINRA BrokerCheck.
    if "broker_dealer" in selected:
        entries.extend(
            [
                (
                    "finra_brokercheck_individual",
                    _source_result(
                        search_brokercheck_individuals(
                            name, normalized_state, client=client
                        ),
                        fragility_note=UNDOCUMENTED_API_NOTE,
                    ),
                ),
                (
                    "finra_brokercheck_firm",
                    _source_result(
                        search_brokercheck_firms(name, normalized_state, client=client),
                        fragility_note=UNDOCUMENTED_API_NOTE,
                    ),
                ),
            ]
        )

    # 2. SEC IAPD.
    if "adviser" in selected:
        entries.extend(
            [
                (
                    "sec_iapd_individual",
                    _source_result(
                        search_iapd_individuals(name, normalized_state, client=client),
                        fragility_note=UNDOCUMENTED_API_NOTE,
                    ),
                ),
                (
                    "sec_iapd_firm",
                    _source_result(
                        search_iapd_firms(name, normalized_state, client=client),
                        fragility_note=UNDOCUMENTED_API_NOTE,
                    ),
                ),
            ]
        )

    # 3. ASC has authoritative downloadable/search data but no official JSON API.
    if "appraiser" in selected:
        entries.append(
            (
                "asc_national_registry",
                _link_out(
                    "https://www.asc.gov/appraiser/advanced",
                    "ASC provides web search and downloads, not an official REST/JSON API; manual link-out in V1.",
                    documentation_url="https://www.asc.gov/resources/public-records",
                ),
            )
        )

    # 4. State real-estate boards: only CO is a genuine V1 API. TREC is honest link-out.
    if "real_estate" in selected:
        if normalized_state == "CO":
            entries.append(
                (
                    "co_dora_real_estate",
                    _source_result(search_co_real_estate(name=name, client=client)),
                )
            )
        elif normalized_state == "TX":
            entries.append(("tx_trec", tx_trec_link_out()))

    # 5. State contractor APIs: TX trades and CO DORA professions only.
    if "contractor" in selected:
        if normalized_state == "TX":
            entries.append(
                ("tx_tdlr", _source_result(search_tx_tdlr(name=name, client=client)))
            )
        elif normalized_state == "CO":
            entries.append(
                (
                    "co_dora_all_professions",
                    _source_result(search_co_all_professions(name=name, client=client)),
                )
            )

    # 6. Explicit web-only gaps.
    if "real_estate" in selected and normalized_state == "GA":
        entries.append(
            (
                "ga_grec",
                _link_out(
                    "https://ata.grec.state.ga.us/Account/Search",
                    "Georgia GREC is web-form-only with no free bulk/API path in V1.",
                ),
            )
        )
    if "real_estate" in selected and normalized_state == "NC":
        entries.append(
            (
                "nc_ncrec",
                _link_out(
                    "https://license.ncrec.gov/ncrec/oecgi3.exe/O4W_LIC_SEARCH_NEW",
                    "North Carolina's free path is web lookup; bulk data requires a paid subscription.",
                ),
            )
        )
    if "contractor" in selected and normalized_state == "GA":
        entries.append(
            (
                "ga_contractors",
                _link_out(
                    "https://verify.sos.ga.gov/Verification",
                    "Georgia contractor verification is web-only in V1.",
                ),
            )
        )
    if "contractor" in selected and normalized_state == "NC":
        entries.append(
            (
                "nc_contractors",
                _link_out(
                    "https://portal.nclbgc.org/Public/Search",
                    "North Carolina general-contractor verification is web-only in V1.",
                ),
            )
        )
    if "real_estate" in selected and normalized_state not in {"CO", "TX", "GA", "NC"}:
        entries.append(
            (
                "state_real_estate",
                _link_out(
                    "",
                    "No genuinely-API state real-estate source applies in V1; provide a covered state or verify with its board.",
                ),
            )
        )
    if "contractor" in selected and normalized_state not in {"CO", "TX", "GA", "NC"}:
        entries.append(
            (
                "state_contractor",
                _link_out(
                    "",
                    "No genuinely-API state contractor source applies in V1; contractor licensing is state and often municipal.",
                ),
            )
        )

    # 7. NMLS must remain link-out only; its public site forbids production scraping.
    if "mlo" in selected:
        entries.append(
            (
                "nmls_consumer_access",
                _link_out(
                    nmls_deep_link(name),
                    "NMLS is link-out only: there is no free public API, its free data is lookup-format, automated scraping presents Terms-of-Use risk, and the B2B feed is paid.",
                    b2b_url=(
                        "https://mortgage.nationwidelicensingsystem.org/about/"
                        "sitepages/NMLSB2BAccess.aspx"
                    ),
                ),
            )
        )

    pending = [value for _, value in entries if asyncio.iscoroutine(value)]
    resolved = await asyncio.gather(*pending) if pending else []
    resolved_iter = iter(resolved)
    sources: dict[str, dict[str, Any]] = {}
    for source_name, value in entries:
        sources[source_name] = next(resolved_iter) if asyncio.iscoroutine(value) else value

    return {
        "query": {"name": name.strip(), "state": normalized_state, "roles": list(selected)},
        "sources": sources,
        "candidate_match_count": sum(
            len(result.get("candidates", [])) for result in sources.values()
        ),
        "disciplinary_summary": _disciplinary_summary(sources),
        "identity_caveat": {
            "candidate_matches_only": True,
            "same_name_collisions_possible": True,
            "text": IDENTITY_CAVEAT,
        },
        "no_match_caveat": NO_MATCH_CAVEAT,
    }


__all__ = ["DEFAULT_ROLES", "nmls_deep_link", "verify_counterparty"]
