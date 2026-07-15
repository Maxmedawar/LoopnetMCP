"""Deterministic title-commitment issue extraction.

The output is a routing aid for a title company, counsel, and a surveyor.  It
does not opine on title, coverage, enforceability, priority, or whether an item
can actually be cured, deleted, or endorsed.  Every positive document finding
retains a quote and line-based locator; a silent document is reported as
missing rather than filled with assumed language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cre_mcp.truth.sanitize import sanitize_text


_POSTURE = (
    "ISSUE LIST ONLY — this deterministic screen is not a title opinion or legal "
    "conclusion. The title company controls commitment and policy coverage; counsel "
    "and the surveyor must review matters within their professional scope."
)

_GAP_NOTE = (
    "Gap convention: a commitment reports through its stated effective date only. "
    "Ask the title company for a date-down/update through closing and recording, and "
    "ask counsel/title company what gap coverage and recording procedures apply."
)

_SECTION_A = "schedule_a"
_SECTION_BI = "schedule_b_i"
_SECTION_BII = "schedule_b_ii"


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int
    number: int


def _lines(text: str) -> list[_Line]:
    result: list[_Line] = []
    offset = 0
    # splitlines(keepends=True) preserves source offsets and also behaves well
    # for a final line without a newline.
    raw_lines = text.splitlines(keepends=True)
    if text and not raw_lines:
        raw_lines = [text]
    for number, raw in enumerate(raw_lines, start=1):
        value = raw.rstrip("\r\n")
        result.append(_Line(value, offset, offset + len(value), number))
        offset += len(raw)
    return result


def _heading_key(value: str) -> str | None:
    compact = " ".join(value.strip().split())
    if not compact:
        return None
    if re.fullmatch(r"(?:ALTA\s+)?(?:TITLE\s+)?SCHEDULE\s+A(?:\s*[-:—].*)?", compact, re.I):
        return _SECTION_A

    schedule_b_part = re.search(
        r"\bSCHEDULE\s+B\s*(?:[,.:\-—]\s*)?(?:PART\s*)?(II|2|I|1)\b",
        compact,
        re.I,
    )
    if schedule_b_part:
        return _SECTION_BII if schedule_b_part.group(1).upper() in {"II", "2"} else _SECTION_BI
    if re.fullmatch(r"(?:PART\s+)?II\s*[-:—]?\s*(?:EXCEPTIONS(?:\s+FROM\s+COVERAGE)?)?", compact, re.I):
        return _SECTION_BII
    if re.fullmatch(r"(?:PART\s+)?I\s*[-:—]?\s*(?:REQUIREMENTS)?", compact, re.I):
        return _SECTION_BI
    if re.fullmatch(r"(?:SCHEDULE\s+B\s*[-:—]?\s*)?EXCEPTIONS(?:\s+FROM\s+COVERAGE)?", compact, re.I):
        return _SECTION_BII
    if re.fullmatch(r"(?:SCHEDULE\s+B\s*[-:—]?\s*)?REQUIREMENTS", compact, re.I):
        return _SECTION_BI
    if re.fullmatch(r"SCHEDULE\s+B", compact, re.I):
        return "schedule_b_pending"
    return None


def _partition(lines: list[_Line]) -> tuple[dict[str, list[_Line]], set[str]]:
    sections = {_SECTION_A: [], _SECTION_BI: [], _SECTION_BII: []}
    present: set[str] = set()
    current: str | None = None
    for line in lines:
        heading = _heading_key(line.text)
        if heading:
            current = heading
            if heading != "schedule_b_pending":
                present.add(heading)
            continue
        if current in sections:
            sections[current].append(line)
    return sections, present


def _locator(section: str, start_line: int, end_line: int | None = None, item: str | None = None) -> str:
    label = {
        _SECTION_A: "Schedule A",
        _SECTION_BI: "Schedule B-I",
        _SECTION_BII: "Schedule B-II",
    }.get(section, "commitment")
    line_label = f"line {start_line}" if end_line in (None, start_line) else f"lines {start_line}-{end_line}"
    item_label = f", item {item}" if item else ""
    return f"{label}{item_label}, {line_label}"


def _finding(value: Any, quote: str, section: str, start_line: int, end_line: int | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "quote": quote.strip(),
        "locator": _locator(section, start_line, end_line),
    }


def _next_value(lines: list[_Line], index: int, *, multiline: bool = False) -> tuple[str | None, int]:
    values: list[str] = []
    end_line = lines[index].number
    for candidate in lines[index + 1 :]:
        stripped = candidate.text.strip()
        if not stripped:
            if values:
                break
            continue
        # A new numbered Schedule A field ends a carried value.  Lot/Block and
        # metes-and-bounds prose ordinarily do not use this label shape.
        if re.match(r"^\s*\d+[.)]\s+[A-Za-z]", candidate.text) and values:
            break
        values.append(stripped)
        end_line = candidate.number
        if not multiline:
            break
    return (" ".join(values) or None), end_line


def _labeled(
    lines: list[_Line],
    pattern: re.Pattern[str],
    *,
    section: str = _SECTION_A,
    multiline: bool = False,
) -> dict[str, Any] | None:
    for index, line in enumerate(lines):
        match = pattern.search(line.text)
        if not match:
            continue
        value = (match.groupdict().get("value") or "").strip(" \t:;,-") or None
        end_line = line.number
        quote_lines = [line.text.strip()]
        if value is None:
            value, end_line = _next_value(lines, index, multiline=multiline)
            if end_line > line.number:
                quote_lines.extend(
                    candidate.text.strip()
                    for candidate in lines[index + 1 :]
                    if line.number < candidate.number <= end_line and candidate.text.strip()
                )
        return _finding(value, "\n".join(quote_lines), section, line.number, end_line)
    return None


_EFFECTIVE = re.compile(
    r"\b(?:Commitment|Effective)\s+Date(?:\s+and\s+Time)?\b\s*(?:is\s*)?[:\-]\s*(?P<value>.*)$",
    re.I,
)
_INSURED = re.compile(
    r"\b(?:Name\s+of\s+)?(?:the\s+)?Proposed\s+Insured(?:\(s\)|s)?\b\s*(?:is\s*)?[:\-]\s*(?P<value>.*)$",
    re.I,
)
_ESTATE = re.compile(
    r"\bEstate\s+or\s+Interest\b.*?(?:\bis\s*)?[:\-]\s*(?P<value>.*)$",
    re.I,
)
_VESTED = re.compile(
    r"\b(?:Title\s+to\s+the\s+estate\s+or\s+interest.*?vested\s+in|"
    r"(?:Fee\s+)?Title\s+(?:is\s+)?vested\s+in|Vested\s+Owner)\b\s*[:\-]?\s*(?P<value>.*)$",
    re.I,
)
_LEGAL = re.compile(
    r"\b(?:Legal\s+Description(?:\s+of\s+(?:the\s+)?Land)?|"
    r"The\s+Land(?:\s+referred\s+to\s+in\s+this\s+Commitment)?\s+is\s+described\s+as\s+follows)"
    r"\b\s*[:\-]?\s*(?P<value>.*)$",
    re.I,
)


def _legal_description(lines: list[_Line]) -> dict[str, Any]:
    labeled = _labeled(lines, _LEGAL, multiline=True)
    if labeled is not None:
        value = labeled["value"]
        return {
            **labeled,
            "present": value is not None,
            "reference_only": bool(value and re.search(r"\bsee\s+(?:attached\s+)?exhibit\b", value, re.I)),
        }

    description_language = re.compile(
        r"\b(?:Lot\s+\d+.*\bBlock\s+\w+|Beginning\s+at\b|A\s+tract\s+of\s+land\b)",
        re.I,
    )
    for line in lines:
        if description_language.search(line.text):
            return {
                **_finding(line.text.strip(), line.text, _SECTION_A, line.number),
                "present": True,
                "reference_only": False,
            }
    return {"value": None, "present": False, "reference_only": None, "quote": None, "locator": None}


def _numbered_items(lines: list[_Line], section: str) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.text.strip()
        if not stripped:
            continue
        match = re.match(r"^\s*(?:\((?P<paren>\d+)\)|(?P<number>\d+)[.)])\s*(?P<body>.*)$", line.text)
        if match:
            if current is not None:
                groups.append(current)
            current = {
                "number": match.group("paren") or match.group("number"),
                "lines": [line],
            }
            continue
        if current is None:
            # Unnumbered commitments exist. Treat each paragraph-leading line as
            # an item instead of silently losing it.
            current = {"number": str(len(groups) + 1), "lines": [line]}
        else:
            current["lines"].append(line)
    if current is not None:
        groups.append(current)

    result: list[dict[str, Any]] = []
    for group in groups:
        item_lines: list[_Line] = group["lines"]
        quote = "\n".join(line.text.strip() for line in item_lines).strip()
        result.append(
            {
                "item_number": group["number"],
                "quote": quote,
                "locator": _locator(
                    section,
                    item_lines[0].number,
                    item_lines[-1].number,
                    group["number"],
                ),
            }
        )
    return result


_DEADLINE = re.compile(
    r"\b(?:on\s+or\s+before|no\s+later\s+than|prior\s+to|before|at|by|within)\b"
    r"[^.;\n]{0,90}\b(?:closing|recording|issuance|\d{4}|days?)\b",
    re.I,
)


def _requirement_actors(text: str) -> list[str]:
    lowered = text.casefold()
    actors: list[str] = []
    for token, actor in (
        ("proposed insured", "proposed insured"),
        ("buyer", "buyer/proposed insured"),
        ("purchaser", "buyer/proposed insured"),
        ("seller", "seller/current owner"),
        ("owner", "seller/current owner"),
        ("lender", "lender"),
        ("borrower", "borrower"),
        ("title company", "title company"),
    ):
        if token in lowered and actor not in actors:
            actors.append(actor)
    if re.search(r"\b(?:survey|plat)\b", lowered):
        actors.extend(actor for actor in ("surveyor", "buyer/proposed insured") if actor not in actors)
    if re.search(r"\b(?:release|satisf(?:y|action)|payoff|mortgage|deed\s+of\s+trust|lien)\b", lowered):
        actors.extend(
            actor
            for actor in ("seller/current owner", "lienholder", "title company")
            if actor not in actors
        )
    if re.search(r"\b(?:tax|assessment)\b", lowered):
        actors.extend(actor for actor in ("seller/current owner", "title company") if actor not in actors)
    if re.search(r"\b(?:deed|execute|execution|document)\b", lowered):
        actors.extend(actor for actor in ("document parties", "title company") if actor not in actors)
    if re.search(r"\b(?:affidavit|indemnity)\b", lowered):
        actors.extend(actor for actor in ("required signer/affiant", "title company") if actor not in actors)
    if re.search(r"\b(?:premium|charges?|fees?)\b", lowered):
        actors.extend(actor for actor in ("buyer/proposed insured", "title company") if actor not in actors)
    return actors or ["title company", "buyer/proposed insured and/or seller", "counsel"]


def _requirement_cure(text: str) -> str:
    lowered = text.casefold()
    if re.search(r"\b(?:release|satisf(?:y|action)|payoff|mortgage|deed\s+of\s+trust|lien)\b", lowered):
        action = "obtain a title-company-approved payoff, satisfaction, or recordable release and confirm deletion in the marked commitment"
    elif re.search(r"\b(?:tax|assessment)\b", lowered):
        action = "confirm payment/proration evidence and ask the title company what tax clearance or limitation it requires"
    elif re.search(r"\b(?:survey|plat)\b", lowered):
        action = "deliver the survey/plat in the title company's required form and resolve identified discrepancies with the surveyor and counsel"
    elif re.search(r"\b(?:deed|execute|execution|document)\b", lowered):
        action = "deliver the correctly executed, acknowledged, and recordable document in the form accepted by the title company and counsel"
    elif re.search(r"\b(?:affidavit|indemnity)\b", lowered):
        action = "deliver the requested signed affidavit or indemnity only after counsel reviews its statements and risk allocation"
    elif re.search(r"\b(?:premium|charges?|fees?)\b", lowered):
        action = "confirm the title invoice and arrange payment of the accepted premium and charges"
    else:
        action = "ask the title company to identify the evidence or instrument required and have counsel confirm the proposed response"
    return f"Typical cure convention only: {action}; the commitment's actual terms control."


def _classify_exception(text: str) -> str:
    lowered = text.casefold()
    patterns = (
        ("taxes", r"\b(?:tax(?:es)?|assessment(?:s)?|special\s+district|ad\s+valorem)\b"),
        ("easement", r"\b(?:easement|right[- ]of[- ]way|access\s+rights?|ingress|egress)\b"),
        ("mineral", r"\b(?:mineral|oil|gas|hydrocarbon|subsurface|royalt(?:y|ies))\b"),
        ("lien", r"\b(?:lien|mortgage|deed\s+of\s+trust|judgment|financing\s+statement|ucc)\b"),
        ("lease", r"\b(?:lease|tenant|lessee|lessor|memorandum\s+of\s+lease)\b"),
        (
            "covenant",
            r"\b(?:covenants?|conditions?|restrictions?|declarations?|"
            r"cc\s*&\s*rs?|maintenance\s+agreements?)\b",
        ),
        ("survey", r"\b(?:survey|encroach|overlap|boundary|shortage\s+in\s+area|discrepanc|setback)\b"),
    )
    for classification, pattern in patterns:
        if re.search(pattern, lowered):
            return classification
    return "standard"


_EXCEPTION_GUIDANCE = {
    "standard": (
        "Ask the title company which standard exception can be deleted or limited and "
        "what affidavit, survey, or other evidence it requires."
    ),
    "survey": (
        "Ask the surveyor to locate the matter and ask the title company to delete or "
        "limit it based on an accepted survey and identify available survey endorsements."
    ),
    "taxes": (
        "Confirm payment and proration, then ask the title company to limit the exception "
        "to taxes not yet due and payable if its underwriting permits."
    ),
    "easement": (
        "Obtain the recorded instrument, have the surveyor plot it and counsel review its "
        "scope, then ask the title company whether deletion, limitation, or an endorsement is available."
    ),
    "mineral": (
        "Obtain the severance/reservation instrument and surface-rights evidence; ask counsel "
        "about use impact and the title company whether deletion, limitation, or an endorsement is available."
    ),
    "lien": (
        "Arrange title-company-approved payoff/release evidence and ask the title company to "
        "delete the item from the final policy if its underwriting requirements are met."
    ),
    "lease": (
        "Obtain the lease and amendments, confirm status with counsel/estoppel evidence, and "
        "ask the title company to delete a terminated or inapplicable item if supported."
    ),
    "covenant": (
        "Obtain the complete recorded instrument and amendments, route use restrictions to "
        "counsel, and ask the title company about deletion, limitation, or available endorsements."
    ),
}


def _parse(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    sanitized = sanitize_text(text)
    all_lines = _lines(sanitized.text)
    sections, present = _partition(all_lines)
    schedule_a_lines = sections[_SECTION_A]

    effective = _labeled(schedule_a_lines, _EFFECTIVE)
    if effective is None:
        # Some commitments place the commitment date on the cover page.
        effective = _labeled(all_lines, _EFFECTIVE, section="commitment")
    insured = _labeled(schedule_a_lines, _INSURED)
    estate = _labeled(schedule_a_lines, _ESTATE)
    vested_owner = _labeled(schedule_a_lines, _VESTED)
    legal = _legal_description(schedule_a_lines)

    requirements = []
    for item in _numbered_items(sections[_SECTION_BI], _SECTION_BI):
        deadline = _DEADLINE.search(item["quote"])
        requirements.append(
            {
                **item,
                "who_must_act": _requirement_actors(item["quote"]),
                "deadline": deadline.group(0).strip() if deadline else None,
                "typical_cure_note": _requirement_cure(item["quote"]),
                "cure_is_convention": True,
                "counsel_review_required": True,
            }
        )

    exceptions = []
    for item in _numbered_items(sections[_SECTION_BII], _SECTION_BII):
        classification = _classify_exception(item["quote"])
        exceptions.append(
            {
                **item,
                "classification": classification,
                "title_company_guidance": _EXCEPTION_GUIDANCE[classification],
                "guidance_is_convention": True,
                "counsel_review_required": True,
            }
        )

    schedule_a = {
        "insured": insured,
        "estate_or_interest": estate,
        "vested_owner": vested_owner,
        "legal_description": legal,
    }
    missing: list[str] = []
    if _SECTION_A not in present:
        missing.append("schedule_a")
    if insured is None:
        missing.append("schedule_a.insured")
    if estate is None:
        missing.append("schedule_a.estate_or_interest")
    if not legal["present"]:
        missing.append("schedule_a.legal_description")
    if effective is None:
        missing.append("effective_date")
    if not requirements:
        missing.append("schedule_b_i.requirements")
    if not exceptions:
        missing.append("schedule_b_ii.exceptions")

    gap_review = {
        "status": "update_required" if effective is not None else None,
        "effective_date": effective["value"] if effective else None,
        "quote": effective["quote"] if effective else None,
        "locator": effective["locator"] if effective else None,
        "note": _GAP_NOTE,
    }
    return {
        "effective_date": effective,
        "gap_note": _GAP_NOTE,
        "gap_review": gap_review,
        "schedule_a": schedule_a,
        "requirements": requirements,
        "exceptions": exceptions,
        # Explicit aliases keep the output natural for both checklist and ALTA
        # terminology without changing the issue objects themselves.
        "schedule_b_i": requirements,
        "schedule_b_ii": exceptions,
        "schedule_b": {
            "part_i_requirements": requirements,
            "part_ii_exceptions": exceptions,
        },
        "missing": missing,
        "sanitization_redactions": sanitized.redactions,
        "conventions": {
            "requirement_cures": "Typical examples only; title company and counsel control the required response.",
            "exception_classification": (
                "Keyword routing only; a single instrument can implicate multiple classes, and "
                "the title company/counsel must review the complete instrument."
            ),
            "gap": _GAP_NOTE,
        },
        "title_company_review_required": True,
        "counsel_review_required": True,
        "honesty": _POSTURE,
    }


def parse_title_commitment(text: str) -> dict[str, Any]:
    """Parse cited Schedule A, B-I, and B-II commitment issues.

    Invalid input and unexpected failures are contained at the public boundary
    as ``{"error": ...}`` so this plain function is safe to expose through the
    separate tools module.
    """

    try:
        return _parse(text)
    except Exception as exc:  # boundary containment is intentional
        return {"error": str(exc)}


__all__ = ["parse_title_commitment"]
