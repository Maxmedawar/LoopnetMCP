"""Deterministic, cited extraction of lease and CC&R use restrictions.

This is a screening extractor, not a legal interpreter.  Positive findings are
bounded, verbatim spans from sanitized text.  A clause category with no finding
is listed in :attr:`RestrictionSet.missing_fields`; no market-standard language
is supplied for a silent document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from cre_mcp.leases.models import CitedClaim
from cre_mcp.truth.sanitize import sanitize_text

RestrictionKind = Literal["lease", "ccr"]

_NUMBER_WORDS = {
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "fifteen": 15.0,
    "twenty": 20.0,
}


@dataclass
class RestrictionSet:
    """Cited restrictions extracted from one lease or recorded CC&R document."""

    kind: RestrictionKind
    exclusive_uses: list[CitedClaim] = field(default_factory=list)
    prohibited_uses: list[CitedClaim] = field(default_factory=list)
    radius_restrictions: list[CitedClaim] = field(default_factory=list)
    cotenancy_conditions: list[CitedClaim] = field(default_factory=list)
    continuous_operation_requirements: list[CitedClaim] = field(default_factory=list)
    go_dark_rights: list[CitedClaim] = field(default_factory=list)
    rofr_rofo_rights: list[CitedClaim] = field(default_factory=list)
    assignment_subletting_clauses: list[CitedClaim] = field(default_factory=list)
    use_clauses: list[CitedClaim] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    sanitization_redactions: int = 0

    def _first(self, values: list[CitedClaim]) -> CitedClaim:
        return values[0] if values else CitedClaim.missing(source=self.kind)

    # Singular and alternate aliases make the model pleasant for callers while
    # retaining every separately cited clause in the canonical list fields.
    @property
    def exclusive_use(self) -> CitedClaim:
        return self._first(self.exclusive_uses)

    @property
    def exclusive_use_grants(self) -> list[CitedClaim]:
        return self.exclusive_uses

    @property
    def prohibited_use(self) -> CitedClaim:
        return self._first(self.prohibited_uses)

    @property
    def radius_restriction(self) -> CitedClaim:
        return self._first(self.radius_restrictions)

    @property
    def co_tenancy(self) -> CitedClaim:
        return self._first(self.cotenancy_conditions)

    @property
    def continuous_operation(self) -> CitedClaim:
        return self._first(self.continuous_operation_requirements)

    @property
    def go_dark(self) -> CitedClaim:
        return self._first(self.go_dark_rights)

    @property
    def rofr_rofo(self) -> CitedClaim:
        return self._first(self.rofr_rofo_rights)

    @property
    def assignment_subletting(self) -> list[CitedClaim]:
        return self.assignment_subletting_clauses

    @property
    def assignment_subletting_standard(self) -> CitedClaim:
        """Return the most restrictive cited standard, without legal inference."""
        if not self.assignment_subletting_clauses:
            return CitedClaim.missing(source=self.kind)
        priority = {
            "prohibited": 0,
            "consent_required": 1,
            "consent_not_unreasonably_withheld": 2,
            "conditional_free": 3,
            "free": 4,
            "change_of_control_exception": 5,
            "unclear": 6,
        }
        return min(
            self.assignment_subletting_clauses,
            key=lambda claim: priority.get(str((claim.value or {}).get("standard")), 99),
        )

    @property
    def use_clause(self) -> CitedClaim:
        return self._first(self.use_clauses)


class _TextView:
    """Whitespace-compacted search text mapped to exact sanitized offsets."""

    def __init__(self, source: str, *, kind: RestrictionKind) -> None:
        self.source = source
        self.kind = kind
        chars: list[str] = []
        offsets: list[int] = []
        in_space = False
        for offset, char in enumerate(source):
            if char.isspace():
                if chars and not in_space:
                    chars.append(" ")
                    offsets.append(offset)
                in_space = True
            else:
                chars.append(char)
                offsets.append(offset)
                in_space = False
        self.text = "".join(chars)
        self.offsets = offsets

    def _raw_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.offsets:
            return 0, 0
        start = min(max(start, 0), len(self.offsets) - 1)
        end_index = min(max(end - 1, start), len(self.offsets) - 1)
        return self.offsets[start], self.offsets[end_index] + 1

    def locator(self, start: int, end: int) -> str:
        raw_start, raw_end = self._raw_span(start, end)
        line = self.source.count("\n", 0, raw_start) + 1
        return f"{self.kind} line {line}, chars {raw_start}-{raw_end}"

    def claim(
        self,
        value: Any,
        start: int,
        end: int,
        *,
        confidence: float,
        status: Literal["stated", "inferred"] = "stated",
    ) -> CitedClaim:
        raw_start, raw_end = self._raw_span(start, end)
        quote = self.source[raw_start:raw_end].strip()[:200]
        locator = self.locator(start, end)
        if status == "inferred":
            return CitedClaim.inferred(
                value,
                quote=quote,
                locator=locator,
                confidence=confidence,
                source=self.kind,
            )
        return CitedClaim.stated(
            value,
            quote=quote,
            locator=locator,
            confidence=confidence,
            source=self.kind,
        )

    def clause(self, match: re.Match[str], *, before: int = 120, after: int = 700) -> tuple[str, int, int]:
        start_floor = max(0, match.start() - before)
        prior = max(
            self.text.rfind(". ", start_floor, match.start()),
            self.text.rfind("; ", start_floor, match.start()),
        )
        start = prior + 2 if prior >= 0 else start_floor
        end_ceiling = min(len(self.text), match.end() + after)
        period = self.text.find(". ", match.end(), end_ceiling)
        end = period + 1 if period >= 0 else end_ceiling
        return self.text[start:end].strip(), start, end


def _dedupe(claims: list[CitedClaim]) -> list[CitedClaim]:
    result: list[CitedClaim] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim.quote.casefold(), repr(claim.value))
        if key not in seen:
            seen.add(key)
            result.append(claim)
    return result


def _clean(value: str, *, limit: int = 700) -> str:
    return " ".join(value.split()).strip(" ,.;:")[:limit]


def _numeric(raw: str | None) -> float | None:
    if not raw:
        return None
    paren = re.search(r"\((\d+(?:\.\d+)?)\)", raw)
    if paren:
        return float(paren.group(1))
    digit = re.search(r"\d+(?:\.\d+)?", raw)
    if digit:
        return float(digit.group(0))
    return _NUMBER_WORDS.get(raw.casefold().strip())


def _subject(clause: str) -> str:
    patterns = (
        r"(?P<v>[A-Z][A-Za-z0-9&' .-]{1,70}|Tenant)\s+(?:shall|will|may)\s+have\s+"
        r"(?:an?\s+)?exclusive",
        r"(?P<v>[A-Z][A-Za-z0-9&' .-]{1,70}|Tenant)\s+(?:shall|may)\s+not\s+"
        r"(?:operate|open|own)",
        r"in\s+favor\s+of\s+(?P<v>[A-Z][A-Za-z0-9&' .-]{1,70}|Tenant)",
    )
    for pattern in patterns:
        match = re.search(pattern, clause)
        if match:
            return _clean(match.group("v"), limit=80)
    return "Tenant or benefited party not named in extracted span"


def _extract_use_clauses(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    labeled = re.compile(
        r"\b(?:Permitted\s+Use|Use\s+Clause)\b\s*:?\s*(?P<v>.{1,1000}?)"
        r"(?=\s+(?:\d{1,2}|[A-Z])[.)]\s+[A-Z]|\Z)",
        re.I,
    )
    for match in labeled.finditer(view.text):
        body = _clean(match.group("v"))
        if body:
            claims.append(
                view.claim(
                    {"scope": body},
                    *match.span("v"),
                    confidence=0.9,
                )
            )
    use_sentence = re.compile(
        r"(?:use\s+of\s+(?:the\s+)?premises|premises\s+(?:shall|will|may)\s+be\s+used)"
        r".{0,500}",
        re.I,
    )
    for match in use_sentence.finditer(view.text):
        clause, start, end = view.clause(match, before=30, after=520)
        claims.append(
            view.claim({"scope": _clean(clause)}, start, end, confidence=0.8)
        )
    return _dedupe(claims)


def _extract_exclusives(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    patterns = (
        re.compile(r"\bexclusive\s+(?:use|right|privilege)\b", re.I),
        re.compile(
            r"\bLandlord\s+(?:shall|will|covenants?\s+to)\s+not\s+"
            r"(?:lease|rent|permit|allow).{0,180}?(?:use|business|tenant)",
            re.I,
        ),
        re.compile(r"\bno\s+other\s+(?:tenant|occupant).{0,180}?(?:use|sell|operate)", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(view.text):
            clause, start, end = view.clause(match, before=150, after=700)
            scope_match = re.search(
                r"(?:exclusive\s+(?:use|right|privilege)(?:\s+to)?|"
                r"not\s+(?:lease|rent|permit|allow)[^.]{0,180}?(?:for|as|to))\s+(?P<v>.+)",
                clause,
                re.I,
            )
            scope = _clean(scope_match.group("v") if scope_match else clause)
            claims.append(
                view.claim(
                    {"holder": _subject(clause), "scope": scope},
                    start,
                    end,
                    confidence=0.88 if "exclusive" in clause.casefold() else 0.81,
                )
            )
    return _dedupe(claims)


def _extract_prohibited_uses(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    patterns = (
        re.compile(r"\bprohibited\s+uses?\b", re.I),
        re.compile(r"\b(?:premises|property|parcel|lot|tract)\s+shall\s+not\s+be\s+used\s+for\b", re.I),
        re.compile(r"\bno\s+(?:portion|part)\s+of.{0,80}?shall\s+be\s+used\s+for\b", re.I),
        re.compile(r"\buse\s+of.{0,80}?\bis\s+(?:expressly\s+)?prohibited\b", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(view.text):
            clause, start, end = view.clause(match, before=100, after=650)
            # A landlord promise not to lease competing space is captured as an
            # exclusive grant, not duplicated as a generally prohibited use.
            if re.search(r"Landlord.{0,80}?not\s+(?:lease|rent|permit)", clause, re.I):
                continue
            uses_match = re.search(
                r"(?:prohibited\s+uses?\s*(?:include|are|:)?|shall\s+not\s+be\s+used\s+for|"
                r"is\s+(?:expressly\s+)?prohibited)\s*(?P<v>.+)",
                clause,
                re.I,
            )
            scope = _clean(uses_match.group("v") if uses_match else clause)
            claims.append(
                view.claim({"uses": scope}, start, end, confidence=0.88)
            )
    return _dedupe(claims)


def _extract_radius(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bRadius\s+Restriction\b|\bwithin\s+"
        r"(?:[A-Za-z]+(?:\s*\(\d+(?:\.\d+)?\))?|\d+(?:\.\d+)?)\s+miles?\b|"
        r"\bradius\s+of\s+(?:[A-Za-z]+(?:\s*\(\d+(?:\.\d+)?\))?|\d+(?:\.\d+)?)\s+miles?\b",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=180, after=520)
        number_match = re.search(
            r"(?:within|radius\s+of)\s+(?P<v>[A-Za-z]+(?:\s*\(\d+(?:\.\d+)?\))?|"
            r"\d+(?:\.\d+)?)\s+miles?",
            clause,
            re.I,
        )
        none = bool(re.search(r"Radius\s+Restriction\s*:\s*(?:None|N/?A|Not\s+Applicable)", clause, re.I))
        value = {
            "radius_miles": None if none else _numeric(number_match.group("v") if number_match else None),
            "holder": _subject(clause),
            "scope": "none" if none else _clean(clause),
            "restricted": not none,
        }
        claims.append(view.claim(value, start, end, confidence=0.91 if none or number_match else 0.75))
    return _dedupe(claims)


def _extract_cotenancy(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bco[- ]tenancy\b|\banchor\s+tenant\b.{0,180}?\b(?:open|operating)\b|"
        r"\b(?:occupancy|occupied)\b.{0,80}?\d+(?:\.\d+)?\s*%",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=100, after=850)
        anchor_matches = re.findall(
            r"(?:anchor\s+tenant\s+|named\s+tenant\s+)?"
            r"([A-Z][A-Za-z0-9&' .-]{1,55})\s+(?:must|shall)\s+(?:remain|be)\s+"
            r"(?:open|operating)",
            clause,
        )
        anchors = [_clean(item, limit=60) for item in anchor_matches]
        threshold = re.search(
            r"(?P<v>\d+(?:\.\d+)?)\s*%[^.]{0,80}?(?:occupied|occupancy)|"
            r"(?:occupied|occupancy)[^.%]{0,80}?(?P<v2>\d+(?:\.\d+)?)\s*%",
            clause,
            re.I,
        )
        threshold_pct = None
        if threshold:
            threshold_pct = float(threshold.group("v") or threshold.group("v2"))
        remedies: list[str] = []
        remedy_patterns = (
            ("rent_reduction", r"reduc(?:e|ed|tion)|alternative\s+rent|substitute\s+rent"),
            ("go_dark", r"go[- ]dark|cease\s+(?:to\s+)?operate"),
            ("termination", r"terminat(?:e|ion)"),
        )
        for label, remedy_pattern in remedy_patterns:
            if re.search(remedy_pattern, clause, re.I):
                remedies.append(label)
        claims.append(
            view.claim(
                {
                    "named_anchors": anchors,
                    "occupancy_threshold_pct": threshold_pct,
                    "remedies": remedies,
                    "condition": _clean(clause),
                },
                start,
                end,
                confidence=0.88 if anchors or threshold_pct is not None else 0.76,
            )
        )
    return _dedupe(claims)


def _extract_continuous_operation(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bcontinu(?:ous|ously)\s+(?:operation|operate)\b|"
        r"\bshall\s+(?:remain|be)\s+open\s+for\s+business\b|"
        r"\bshall\s+operate\b.{0,100}?\bbusiness\s+days\b",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=150, after=500)
        claims.append(
            view.claim(
                {"required": True, "scope": _clean(clause)},
                start,
                end,
                confidence=0.9,
            )
        )
    return _dedupe(claims)


def _extract_go_dark(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bgo[- ]dark\b|\b(?:right|option)\s+to\s+(?:cease|discontinue)\s+(?:operations?|operating)\b|"
        r"\bmay\s+(?:cease|discontinue)\s+(?:operations?|operating)\b",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=140, after=520)
        denied = bool(re.search(r"(?:no\s+right|shall\s+not|may\s+not).{0,70}?(?:go[- ]dark|cease|discontinue)", clause, re.I))
        claims.append(
            view.claim(
                {"allowed": not denied, "conditions": _clean(clause)},
                start,
                end,
                confidence=0.86,
            )
        )
    return _dedupe(claims)


def _extract_rofr_rofo(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bRight\s+of\s+First\s+(?P<kind>Refusal|Offer)\b|\b(?P<short>ROFR|ROFO)\b",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=140, after=700)
        token = (match.group("kind") or match.group("short") or "").casefold()
        right_type = "rofr" if "refusal" in token or token == "rofr" else "rofo"
        low = clause.casefold()
        if re.search(r"\b(?:whole|entire)\s+(?:property|shopping\s+center)\b|\bsale\s+of\s+(?:the\s+)?property\b", low):
            scope = "whole_property"
        elif re.search(r"\b(?:space|premises|suite|unit)\b", low):
            scope = "space"
        else:
            scope = "unknown"
        claims.append(
            view.claim(
                {"right_type": right_type, "holder": _subject(clause), "scope": scope},
                start,
                end,
                confidence=0.9 if scope != "unknown" else 0.78,
            )
        )
    return _dedupe(claims)


def _transfer_standard(clause: str) -> tuple[str, bool | None]:
    low = clause.casefold()
    change_control: bool | None = None
    if re.search(r"change\s+(?:in|of)\s+(?:ownership|control)|transfer\s+of\s+control", low):
        if re.search(r"shall\s+not\s+constitute\s+(?:an?\s+)?assignment|not\s+deemed\s+(?:an?\s+)?assignment", low):
            return "change_of_control_exception", False
        change_control = True
    if re.search(r"not\s+(?:be\s+)?unreasonably\s+(?:withheld|conditioned|delayed)", low):
        return "consent_not_unreasonably_withheld", change_control
    if re.search(r"without\s+(?:the\s+)?(?:landlord(?:'s)?\s+)?(?:prior\s+written\s+)?consent", low):
        if re.search(r"(?:shall|may)\s+not|no\s+(?:assignment|sublease|subletting)", low):
            return "consent_required", change_control
        return "free", change_control
    if re.search(r"(?:prior\s+written\s+)?(?:consent|approval)\s+of\s+(?:the\s+)?landlord", low):
        return "consent_required", change_control
    if re.search(r"right\s+to\s+assign.{0,100}?at\s+any\s+time\s+provided", low):
        return "conditional_free", change_control
    if re.search(r"(?:shall|may)\s+not\s+(?:assign|sublet|transfer)|no\s+(?:assignment|sublease|subletting).{0,80}?(?:permitted|allowed)|absolutely\s+prohibit", low):
        return "prohibited", change_control
    if re.search(r"(?:may|right\s+to)\s+(?:assign|sublet).{0,120}?(?:without\s+consent|at\s+any\s+time)", low):
        return "free", change_control
    return "unclear", change_control


def _extract_assignment(view: _TextView) -> list[CitedClaim]:
    claims: list[CitedClaim] = []
    pattern = re.compile(
        r"\bassign(?:ment|ing)?\b|\bsublet(?:ting)?\b|\bsublease\b|"
        r"\btransfer\s+of\s+control\b|\bchange\s+(?:in|of)\s+(?:ownership|control)\b",
        re.I,
    )
    for match in pattern.finditer(view.text):
        clause, start, end = view.clause(match, before=180, after=780)
        if re.search(r"assignment\s+for\s+the\s+benefit\s+of\s+(?:its\s+)?creditors", clause, re.I):
            continue
        if not re.search(r"\b(?:tenant|lease|premises|landlord|consent|sublet|sublease|control)\b", clause, re.I):
            continue
        standard, change_control = _transfer_standard(clause)
        applies: list[str] = []
        if re.search(r"\bassign", clause, re.I):
            applies.append("assignment")
        if re.search(r"\bsublet|\bsublease", clause, re.I):
            applies.append("sublease")
        if change_control is not None or re.search(r"change\s+(?:in|of)\s+(?:ownership|control)", clause, re.I):
            applies.append("transfer_of_control")
        claims.append(
            view.claim(
                {
                    "standard": standard,
                    "applies_to": sorted(set(applies)),
                    "change_of_control_is_assignment": change_control,
                    "conditions": _clean(clause),
                },
                start,
                end,
                confidence=0.9 if standard != "unclear" else 0.68,
            )
        )
    return _dedupe(claims)


def extract_restrictions(text: str, kind: RestrictionKind) -> RestrictionSet:
    """Extract cited use/transfer restrictions from lease or CC&R text.

    The function is intentionally deterministic and conservative.  It reports
    clause language and structured screening attributes; it does not determine
    enforceability, priority, waiver, amendment effect, or a legal conclusion.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if kind not in {"lease", "ccr"}:
        raise ValueError("kind must be 'lease' or 'ccr'")
    sanitized = sanitize_text(text)
    view = _TextView(sanitized.text, kind=kind)
    result = RestrictionSet(
        kind=kind,
        exclusive_uses=_extract_exclusives(view),
        prohibited_uses=_extract_prohibited_uses(view),
        radius_restrictions=_extract_radius(view),
        cotenancy_conditions=_extract_cotenancy(view),
        continuous_operation_requirements=_extract_continuous_operation(view),
        go_dark_rights=_extract_go_dark(view),
        rofr_rofo_rights=_extract_rofr_rofo(view),
        assignment_subletting_clauses=_extract_assignment(view),
        use_clauses=_extract_use_clauses(view),
        sanitization_redactions=sanitized.redactions,
    )
    field_map = {
        "exclusive_uses": result.exclusive_uses,
        "prohibited_uses": result.prohibited_uses,
        "radius_restrictions": result.radius_restrictions,
        "cotenancy_conditions": result.cotenancy_conditions,
        "continuous_operation_requirements": result.continuous_operation_requirements,
        "go_dark_rights": result.go_dark_rights,
        "rofr_rofo_rights": result.rofr_rofo_rights,
        "assignment_subletting_clauses": result.assignment_subletting_clauses,
        "use_clauses": result.use_clauses,
    }
    result.missing_fields = [name for name, claims in field_map.items() if not claims]
    return result


__all__ = ["RestrictionKind", "RestrictionSet", "extract_restrictions"]
