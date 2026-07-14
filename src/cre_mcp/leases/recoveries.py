"""Deterministic recovery-clause abstraction and tenant billing estimates.

The extractor recognizes common CAM, tax, and insurance constructions without
inventing lease economics from market convention.  Every contractual leaf is a
``CitedClaim``; absent or unparseable language remains explicitly missing.

``estimate_recoverable`` is deliberately an arithmetic layer.  Its caller must
provide annual cost pools, and must ensure that the CAM pool has already been
screened for the cited exclusions.  The result labels that assumption and
surfaces ambiguous cap or allocation language for professional review.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from cre_mcp.leases.models import CitedClaim
from cre_mcp.truth.sanitize import sanitize_text


def _missing() -> CitedClaim:
    return CitedClaim.missing()


@dataclass
class CAMCap:
    """A stated CAM cap and the two independent mechanics needed to apply it."""

    pct: CitedClaim = field(default_factory=_missing)
    cumulative_vs_noncumulative: CitedClaim = field(default_factory=_missing)
    over_base_vs_yoy: CitedClaim = field(default_factory=_missing)


@dataclass
class AuditRight:
    """Tenant audit right, lookback/exercise window, and fee-shifting threshold."""

    right: CitedClaim = field(default_factory=_missing)
    window_months: CitedClaim = field(default_factory=_missing)
    threshold: CitedClaim = field(default_factory=_missing)


@dataclass
class ProRataShare:
    """A stated percentage and/or the lease's allocation formula."""

    stated_pct: CitedClaim = field(default_factory=_missing)
    formula: CitedClaim = field(default_factory=_missing)


@dataclass
class RecoveryTerms:
    """Source-cited CAM, tax, and insurance recovery terms."""

    method: CitedClaim = field(default_factory=_missing)
    cam_recovery: CitedClaim = field(default_factory=_missing)
    cam_cap: CAMCap = field(default_factory=CAMCap)
    base_year: CitedClaim = field(default_factory=_missing)
    admin_fee_pct: CitedClaim = field(default_factory=_missing)
    gross_up_pct: CitedClaim = field(default_factory=_missing)
    exclusions: list[CitedClaim] = field(default_factory=list)
    audit_right: AuditRight = field(default_factory=AuditRight)
    pro_rata_share: ProRataShare = field(default_factory=ProRataShare)
    tax_recovery: CitedClaim = field(default_factory=_missing)
    insurance_recovery: CitedClaim = field(default_factory=_missing)
    professional_review_flags: list[dict[str, object]] = field(default_factory=list)


class _TextView:
    """Whitespace-compacted search text mapped back to verbatim source offsets."""

    def __init__(self, source: str) -> None:
        self.source = source
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

    def _original_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.offsets:
            return 0, 0
        start = min(max(start, 0), len(self.offsets) - 1)
        end = min(max(end - 1, start), len(self.offsets) - 1)
        return self.offsets[start], self.offsets[end] + 1

    def _quote(self, start: int, end: int) -> str:
        raw_start, raw_end = self._original_span(start, end)
        if raw_end - raw_start > 200:
            raw_end = min(len(self.source), raw_start + 200)
        return self.source[raw_start:raw_end].strip()[:200]

    def _locator(self, compact_offset: int) -> str:
        raw_start, raw_end = self._original_span(compact_offset, compact_offset + 1)
        line = self.source.count("\n", 0, raw_start) + 1
        return f"line {line}, chars {raw_start}-{raw_end}"

    def claim(
        self,
        value: object,
        start: int,
        end: int,
        *,
        confidence: float,
        inferred: bool = False,
    ) -> CitedClaim:
        kwargs = {
            "quote": self._quote(start, end),
            "locator": self._locator(start),
            "confidence": confidence,
        }
        if inferred:
            return CitedClaim.inferred(value, **kwargs)
        return CitedClaim.stated(value, **kwargs)


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty-five": 25,
    "twenty five": 25,
    "twenty-four": 24,
    "twenty four": 24,
    "thirty": 30,
    "thirty-six": 36,
    "thirty six": 36,
}


def _number_word(raw: str) -> int | None:
    parenthetical = re.search(r"\((\d+)\)", raw)
    if parenthetical:
        return int(parenthetical.group(1))
    digit = re.search(r"\d+", raw)
    if digit:
        return int(digit.group(0))
    return _NUMBER_WORDS.get(" ".join(raw.casefold().split()))


def _pct(raw: str) -> float:
    return float(raw.replace(",", ".")) / 100.0


def _pct_expression(raw: str) -> float | None:
    """Parse numeric or written percentages, preferring doubled numerals."""
    parenthetical = re.search(r"\(\s*(\d+(?:[.,]\d+)?)\s*%\s*\)", raw)
    if parenthetical:
        return _pct(parenthetical.group(1))
    digit = re.search(r"\d+(?:[.,]\d+)?", raw)
    if digit:
        return _pct(digit.group(0))
    words = re.sub(r"\b(?:per\s*cent|percent)\b", "", raw, flags=re.I)
    words = " ".join(words.strip(" ()").casefold().split())
    number = _NUMBER_WORDS.get(words)
    return number / 100.0 if number is not None else None


def _first(patterns: tuple[str, ...], text: str) -> re.Match[str] | None:
    matches = [match for pattern in patterns if (match := re.search(pattern, text, re.I))]
    return min(matches, key=lambda match: match.start()) if matches else None


def _extract_base_year(view: _TextView) -> CitedClaim:
    match = re.search(
        r"(?:the\s+term\s+)?[\"“]?Base\s+Year[\"”]?\s+"
        r"(?:means|shall\s+mean|shall\s+be|is|:)\s+(?:the\s+)?"
        r"(?P<v>(?:calendar\s+year\s+)?\d{4}(?:\s*[-–]\s*\d{2,4})?)",
        view.text,
        re.I,
    )
    if not match:
        return CitedClaim.missing()
    raw = " ".join(match.group("v").split())
    year = re.fullmatch(r"(?:calendar\s+year\s+)?(\d{4})", raw, re.I)
    value: object = int(year.group(1)) if year else re.sub(r"\s*[-–]\s*", "-", raw)
    return view.claim(value, *match.span(), confidence=0.94)


def _extract_cam_recovery(view: _TextView) -> CitedClaim:
    match = _first(
        (
            r"(?:Common\s+Area\s+(?:Maintenance\s+)?Charge|CAM\s+Charge)[^.]{0,100}?"
            r"Tenant\s+shall\s+pay.{0,120}?(?:pro[- ]?rata|proportionate|percentage)\s+share"
            r".{0,180}?(?:costs|expenses|Common\s+Areas)",
            r"Tenant\s+shall\s+pay.{0,180}?Tenant[’']s\s+(?:monthly\s+)?"
            r"(?:pro[- ]?rata|proportionate|percentage)\s+share.{0,180}?"
            r"(?:Common\s+Area\s+Maintenance|common\s+area\s+(?:maintenance\s+)?costs?|CAM)\b",
            r"Tenant[’']s\s+(?:pro[- ]?rata|proportionate|percentage)\s+share.{0,160}?"
            r"(?:Common\s+Area\s+Maintenance|CAM)\s+(?:Charges?|Costs?)",
            r"Tenant\s+shall\s+(?:pay|reimburse).{0,240}?"
            r"(?:Common\s+Area\s+Maintenance|CAM)\s+(?:Charges?|Costs?)",
            r"Lessee\s+shall\s+pay\s+its\s+proportionate\s+share.{0,220}?"
            r"cost\s+to\s+maintain\s+the\s+common\s+areas",
        ),
        view.text,
    )
    if not match:
        return CitedClaim.missing()
    return view.claim("pro_rata", *match.span(), confidence=0.93)


def _extract_tax_recovery(view: _TextView) -> CitedClaim:
    base_stop = _first(
        (
            r"Tenant[’']s\s+(?:Percentage|Proportionate|Pro[- ]?Rata)\s+Share.{0,220}?"
            r"amount\s+by\s+which.{0,220}?(?:Real\s+Estate\s+)?Taxes.{0,120}?"
            r"exceed.{0,100}?Base\s+Year",
            r"Tenant\s+shall\s+pay.{0,350}?(?:taxes|Tax\s+Expenses).{0,220}?"
            r"(?:in\s+excess\s+of|over).{0,100}?Base\s+Year",
        ),
        view.text,
    )
    if base_stop:
        return view.claim("base_year_stop", *base_stop.span(), confidence=0.94)

    pro_rata = _first(
        (
            r"Tenant\s+shall\s+pay.{0,260}?(?:one[- ]twelfth.{0,120}?)?"
            r"Tenant[’']s\s+pro[- ]?rata\s+share.{0,180}?(?:taxes|assessments)",
            r"(?:CAM|Insurance)\s+and\s+Taxes\s*:.{0,100}?"
            r"(?:Tenant|Lessee)\s+shall\s+pay\s+its\s+proportionate\s+share.{0,180}?"
            r"(?:taxes|insurance)",
            r"Tenant\s+shall\s+pay.{0,220}?Tenant[’']s\s+"
            r"(?:proportionate|percentage)\s+share.{0,160}?(?:real\s+estate\s+)?taxes",
        ),
        view.text,
    )
    if pro_rata:
        return view.claim("pro_rata", *pro_rata.span(), confidence=0.92)
    return CitedClaim.missing()


def _extract_insurance_recovery(view: _TextView) -> CitedClaim:
    included = _first(
        (
            r"Tenant\s+agrees.{0,120}?total\s+cost.{0,100}?insurance.{0,180}?"
            r"included\s+in\s+(?:the\s+)?Common\s+Area\s+[Cc]harge.{0,180}?"
            r"Tenant\s+shall\s+pay\s+its\s+proportionate\s+share",
            r"(?:cost|premiums?)\s+(?:of|for|with\s+respect\s+to).{0,180}?insurance"
            r".{0,200}?(?:shall\s+be|are)\s+included\s+in.{0,120}?"
            r"(?:Common\s+Area\s+Maintenance|CAM)\s+(?:Charges?|Costs?)",
            r"All\s+premiums\s+with\s+respect\s+to\s+such\s+insurance.{0,160}?"
            r"included\s+in\s+Common\s+Area\s+Maintenance\s+Charges",
            r"cost\s+of\s+the\s+premiums.{0,120}?included\s+in.{0,100}?"
            r"common\s+area\s+maintenance\s+costs",
        ),
        view.text,
    )
    if included:
        return view.claim("included_in_cam", *included.span(), confidence=0.94)

    pro_rata = _first(
        (
            r"(?:CAM,?\s+)?Insurance\s+and\s+Taxes\s*:.{0,100}?"
            r"(?:Tenant|Lessee)\s+shall\s+pay\s+its\s+proportionate\s+share.{0,180}?"
            r"(?:taxes|insurance)",
            r"Tenant\s+shall\s+pay.{0,220}?Tenant[’']s\s+"
            r"(?:pro[- ]?rata|proportionate|percentage)\s+share.{0,160}?"
            r"insurance\s+(?:premiums?|costs?|expenses?)",
        ),
        view.text,
    )
    if pro_rata:
        return view.claim("pro_rata", *pro_rata.span(), confidence=0.9)
    return CitedClaim.missing()


def _extract_method(
    view: _TextView,
    cam: CitedClaim,
    tax: CitedClaim,
    insurance: CitedClaim,
) -> CitedClaim:
    explicit = (
        ("nnn", r"\b(?:triple[- ]net|NNN)\b"),
        ("modified_gross", r"\bmodified[- ]gross\b"),
        ("gross", r"\b(?:full[- ]service\s+gross|gross\s+lease)\b"),
    )
    for value, pattern in explicit:
        match = re.search(pattern, view.text, re.I)
        if match:
            return view.claim(value, *match.span(), confidence=0.94)
    if tax.value == "base_year_stop":
        return CitedClaim.inferred(
            "base_year_stop",
            quote=tax.quote,
            locator=tax.locator,
            confidence=min(tax.confidence, 0.86),
        )
    if (
        cam.status != "missing"
        and tax.value == "pro_rata"
        and insurance.value in {"pro_rata", "included_in_cam"}
    ):
        claims = (cam, tax, insurance)
        evidence = max(claims, key=lambda claim: len(claim.quote))
        return CitedClaim.inferred(
            "nnn",
            quote=evidence.quote,
            locator=evidence.locator,
            confidence=0.76,
        )
    return CitedClaim.missing()


def _extract_pro_rata(view: _TextView) -> ProRataShare:
    result = ProRataShare()
    percent = _first(
        (
            r"(?:Tenant[’']s\s+)?(?:Pro[- ]?Rata|Proportionate|Percentage)\s+Share"
            r"\s*(?P<expr>\(\s*\d+(?:[.,]\d+)?\s*%\s*\))",
            r"(?:Tenant[’']s\s+)?(?:Pro[- ]?Rata|Proportionate|Percentage)\s+Share"
            r"\s*(?:shall\s+(?:be|equal)|equals?|means?|is|:|=|of)\s*"
            r"(?P<expr>(?:(?:\d+(?:[.,]\d+)?|[A-Za-z]+(?:[- ]+[A-Za-z]+)?)\s*"
            r"(?:%|per\s*cent|percent))(?:\s*\(\s*\d+(?:[.,]\d+)?\s*%\s*\))?)",
        ),
        view.text,
    )
    if percent:
        value = _pct_expression(percent.group("expr"))
        if value is not None:
            result.stated_pct = view.claim(value, *percent.span(), confidence=0.95)

    fraction = re.search(
        r"(?P<clause>Tenant[’']s\s+(?:pro[- ]?rata|proportionate|percentage)\s+share"
        r".{0,180}?fraction.{0,180}?numerator.{0,300}?"
        r"(?:leasable|rentable|square\s+feet|floor\s+area).{0,260}?denominator.{0,350}?"
        r"(?:gross\s+leasable|rentable|square\s+feet|floor\s+area|Shopping\s+Center))",
        view.text,
        re.I,
    )
    proportion = re.search(
        r"(?P<clause>Tenant[’']s\s+Percentage\s+Share.{0,180}?"
        r"proportion\s+that.{0,260}?(?:leased|demised)\s+premises\s+bears\s+to"
        r".{0,260}?(?:Shopping\s+Center|building|tax\s+lot))",
        view.text,
        re.I,
    )
    service = re.search(
        r"Pro[- ]?rata\s+based\s+on\s+tenants\s+sharing\s+service\s+provided\s+by\s+Landlord",
        view.text,
        re.I,
    )
    ratio = re.search(
        r"(?P<clause>Tenant[’']s\s+Common\s+Area\s+Charge\s+shall\s+be\s+determined"
        r".{0,180}?multiplying.{0,160}?ratio\s+of.{0,220}?square\s+feet\s+within\s+"
        r"(?:the\s+)?Premises\s+to\s+the\s+gross\s+leasable\s+area.{0,180}?"
        r"(?:Shopping\s+Center|buildings?))",
        view.text,
        re.I,
    )
    formula_match = fraction or proportion or service or ratio
    if formula_match:
        value = "tenant_sf / total_sf" if formula_match is not service else "tenants_sharing_service"
        result.formula = view.claim(value, *formula_match.span(), confidence=0.93)
    return result


def _extract_cam_cap(view: _TextView) -> CAMCap:
    result = CAMCap()
    match = _first(
        (
            r"(?:Common\s+Area\s+Maintenance|CAM|Operating\s+(?:Costs|Expenses))"
            r"[^.]{0,300}?(?:will|shall)\s+not\s+exceed(?:\s+more\s+than)?"
            r"[^.]{0,120}?\(\s*(?P<v>\d+(?:[.,]\d+)?)\s*%[^)]*\)[^.]{0,180}",
            r"(?:Common\s+Area\s+Maintenance|CAM|Operating\s+(?:Costs|Expenses))"
            r"[^.]{0,520}?(?:increase[^.]{0,100}?(?:shall\s+)?not\s+exceed|"
            r"shall\s+not\s+increase\s+(?:by\s+)?more\s+than|cap(?:ped)?\s+(?:at|of))"
            r"[^.%]{0,100}?(?P<v>\d+(?:[.,]\d+)?)\s*%[^.]{0,180}",
            r"(?P<v>\d+(?:[.,]\d+)?)\s*%[^.]{0,120}?"
            r"(?:cap\s+on|maximum\s+increase\s+in)[^.]{0,180}?"
            r"(?:Common\s+Area\s+Maintenance|CAM|Operating\s+(?:Costs|Expenses))",
        ),
        view.text,
    )
    if not match:
        return result
    result.pct = view.claim(_pct(match.group("v")), *match.span(), confidence=0.93)
    clause = match.group(0)
    if re.search(r"\bnon[- ]?cumulative\b", clause, re.I):
        result.cumulative_vs_noncumulative = view.claim(
            "noncumulative", *match.span(), confidence=0.94
        )
    elif re.search(r"\bcumulative\b|\bcompound(?:ed|ing)?\b", clause, re.I):
        result.cumulative_vs_noncumulative = view.claim(
            "cumulative", *match.span(), confidence=0.9
        )
    if re.search(r"\b(?:Base\s+Year|initial\s+year|first\s+(?:full\s+)?year)\b", clause, re.I):
        result.over_base_vs_yoy = view.claim("over_base", *match.span(), confidence=0.9)
    elif re.search(
        r"\b(?:year[- ]over[- ]year|prior\s+year|preceding\s+(?:calendar\s+)?year|"
        r"previous\s+(?:calendar\s+)?year)\b",
        clause,
        re.I,
    ):
        result.over_base_vs_yoy = view.claim("yoy", *match.span(), confidence=0.9)
    return result


def _extract_admin_fee(view: _TextView) -> CitedClaim:
    patterns = (
        r"(?:administrative|management)\s+(?:costs?|fees?|charges?)\s+"
        r"(?:equal\s+to|of|in\s+(?:the|an)\s+amount\s+(?:equal\s+to|of)|"
        r"(?:shall\s+)?not\s+to?\s*exceed|(?:shall\s+)?not\s+exceed|at)\s*"
        r"(?P<expr>(?:(?:\d+(?:[.,]\d+)?|[A-Za-z]+(?:[- ]+[A-Za-z]+)?)\s*"
        r"(?:%|per\s*cent|percent)(?:\s*\(\s*\d+(?:[.,]\d+)?\s*%\s*\))?|"
        r"[A-Za-z]+(?:[- ]+[A-Za-z]+)?\s*\(\s*\d+(?:[.,]\d+)?\s*%\s*\)"
        r"(?:\s*(?:per\s*cent|percent))?|\(\s*\d+(?:[.,]\d+)?\s*%\s*\)))",
        r"(?P<v>\d+(?:[.,]\d+)?)\s*%\s+(?:administrative|management)\s+(?:fee|charge)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, view.text, re.I):
            context = view.text[max(0, match.start() - 450):match.end() + 450]
            if re.search(r"\b(?:CAM|Common\s+Area|Operating\s+(?:Costs|Expenses))\b", context, re.I):
                raw = match.groupdict().get("expr") or match.groupdict().get("v")
                value = _pct_expression(raw or "")
                if value is not None:
                    return view.claim(value, *match.span(), confidence=0.9)
    return CitedClaim.missing()


def _admin_fee_is_maximum(claim: CitedClaim) -> bool:
    return claim.status != "missing" and bool(
        re.search(r"\b(?:not\s+to\s+exceed|shall\s+not\s+exceed|maximum|capped?\s+at)\b", claim.quote, re.I)
    )


def _extract_gross_up(view: _TextView) -> CitedClaim:
    match = _first(
        (
            r"gross(?:ed)?[- ]up[^.%]{0,220}?(?P<v>\d+(?:[.,]\d+)?)\s*%",
            r"(?P<v>\d+(?:[.,]\d+)?)\s*%\s+(?:leased|occupied|occupancy)"
            r"[^.]{0,180}?gross(?:ed)?[- ]up",
        ),
        view.text,
    )
    if not match:
        return CitedClaim.missing()
    return view.claim(_pct(match.group("v")), *match.span(), confidence=0.9)


def _extract_exclusions(view: _TextView) -> list[CitedClaim]:
    windows: list[tuple[int, str]] = []
    for lead in re.finditer(
        r"(?:Common\s+Area\s+Maintenance|CAM|Operating\s+(?:Costs|Expenses))"
        r".{0,80}?(?:shall\s+not|does\s+not|do\s+not)[^.]{0,50}?include\s*:?",
        view.text,
        re.I,
    ):
        windows.append((lead.start(), view.text[lead.start():lead.start() + 3200]))
    # Structural carve-outs are often placed in the repair article rather than
    # the CAM definition, but are still recovery exclusions.
    for lead in re.finditer(r"roof\s*\(\s*excluding\s+structural\s+portions\s*\)", view.text, re.I):
        windows.append((lead.start(), view.text[lead.start():lead.end()]))

    category_patterns: tuple[tuple[str, str], ...] = (
        ("capital_expenditures", r"\bcapital\s+expenditures?\b"),
        ("structural", r"\b(?:structural\s+(?:repairs?|portions?|components?)|excluding\s+structural\s+portions)\b"),
        ("debt_service", r"\b(?:interest|amortization)\s+on\s+mortgages?\b|\bdebt\s+costs?\b"),
        ("ground_lease", r"\bground\s+lease\s+payments?\b"),
        ("other_tenant_work", r"\b(?:improvements|repairs|alterations)\s+to\s+spaces?\s+leased\s+to\s+other\s+tenants?\b"),
        ("third_party_reimbursements", r"\breimbursement\s+from\s+insurance\s+proceeds\s+or\s+from\s+a\s+third\s+party\b"),
        ("leasing_costs", r"\b(?:leasing\s+commissions?|tenant\s+allowances?|legal\s+fees\s+for\s+leasing)\b"),
        ("landlord_negligence", r"\b(?:negligence|willful\s+misconduct)\s+of\s+Landlord\b"),
        ("earthquake_flood_insurance", r"\bearthquake\s+and\s+flood\s+insurance\b"),
    )
    results: list[CitedClaim] = []
    seen: set[str] = set()
    for window_start, window in windows:
        for category, pattern in category_patterns:
            if category in seen:
                continue
            match = re.search(pattern, window, re.I)
            if match:
                value: object = {"category": category}
                if category == "capital_expenditures" and re.search(
                    r"capital\s+expenditures?,?\s+except", window[match.start():match.start() + 500], re.I
                ):
                    value = {"category": category, "qualification": "except stated permitted categories"}
                results.append(
                    view.claim(
                        value,
                        window_start + match.start(),
                        window_start + min(len(window), match.end() + 180),
                        confidence=0.9,
                    )
                )
                seen.add(category)

    management = re.search(
        r"management\s+fees?[^.]{0,100}?(?:in\s+excess\s+of|exceed(?:ing)?|greater\s+than)"
        r"[^.%]{0,40}?(?P<v>\d+(?:[.,]\d+)?)\s*%",
        view.text,
        re.I,
    )
    if management and "management_fee" not in seen:
        results.append(
            view.claim(
                {"category": "management_fee", "maximum_pct": _pct(management.group("v"))},
                *management.span(),
                confidence=0.92,
            )
        )
    return results


def _extract_audit_right(view: _TextView) -> AuditRight:
    result = AuditRight()
    match = _first(
        (
            r"Tenant\s+shall\s+have\s+the\s+right\s+to\s+"
            r"(?:audit|inspect|examine|review)[^.]{0,500}?"
            r"(?:records|books|Common\s+Area\s+Maintenance|CAM|Operating\s+Expenses)",
            r"Tenant\s+may\s+(?:audit|inspect|examine|review)[^.]{0,500}?"
            r"(?:records|books|Common\s+Area\s+Maintenance|CAM|Operating\s+Expenses)",
        ),
        view.text,
    )
    if not match:
        return result
    context_start = max(0, match.start() - 150)
    context_end = min(len(view.text), match.end() + 1200)
    context = view.text[context_start:context_end]
    result.right = view.claim(True, *match.span(), confidence=0.95)

    window = re.search(
        r"(?:within|not\s+later\s+than)\s+"
        r"(?P<n>[A-Za-z-]+(?:\s+[A-Za-z-]+)?(?:\s*\(\d+\))?|\d+)\s+"
        r"(?P<unit>months?|years?|days?)[^.]{0,180}?"
        r"(?:receipt|delivery|statement|reconciliation|year[- ]end)",
        context,
        re.I,
    )
    if window:
        number = _number_word(window.group("n"))
        if number is not None:
            unit = window.group("unit").casefold()
            months = number * 12 if unit.startswith("year") else number
            inferred = unit.startswith("day")
            if inferred:
                months = round(number / 30.0, 2)
            result.window_months = view.claim(
                months,
                context_start + window.start(),
                context_start + window.end(),
                confidence=0.84 if inferred else 0.92,
                inferred=inferred,
            )
    else:
        most_recent = re.search(r"for\s+the\s+most\s+recent\s+year", context, re.I)
        if most_recent:
            result.window_months = view.claim(
                12,
                context_start + most_recent.start(),
                context_start + most_recent.end(),
                confidence=0.86,
                inferred=True,
            )

    threshold = re.search(
        r"(?:error|overcharge|overstatement|discrepancy)[^.]{0,180}?"
        r"(?:exceed(?:s|ed)?|greater\s+than|more\s+than|at\s+least)\s*"
        r"(?P<v>\d+(?:[.,]\d+)?)\s*%",
        context,
        re.I,
    )
    if threshold:
        result.threshold = view.claim(
            _pct(threshold.group("v")),
            context_start + threshold.start(),
            context_start + threshold.end(),
            confidence=0.9,
        )
    return result


def extract_recovery_terms(text: str | object) -> RecoveryTerms:
    """Extract source-cited recovery terms from sanitized lease text.

    ``text`` may be a string or the ``LeaseDocument`` returned by
    :func:`cre_mcp.leases.reader.read_lease`.  Raw strings are sanitized using
    the same defensive layer as the lease reader.
    """

    if not isinstance(text, str):
        document_text = getattr(text, "text", None)
        if not isinstance(document_text, str):
            raise TypeError("text must be a string or an object with a string .text attribute")
        text = document_text
    view = _TextView(sanitize_text(text).text)
    cam = _extract_cam_recovery(view)
    tax = _extract_tax_recovery(view)
    insurance = _extract_insurance_recovery(view)
    admin_fee = _extract_admin_fee(view)
    review_flags: list[dict[str, object]] = []
    if _admin_fee_is_maximum(admin_fee):
        review_flags.append(_flag(
            "administrative fee stated as maximum; actual charged rate requires confirmation",
            admin_fee,
        ))
    return RecoveryTerms(
        method=_extract_method(view, cam, tax, insurance),
        cam_recovery=cam,
        cam_cap=_extract_cam_cap(view),
        base_year=_extract_base_year(view),
        admin_fee_pct=admin_fee,
        gross_up_pct=_extract_gross_up(view),
        exclusions=_extract_exclusions(view),
        audit_right=_extract_audit_right(view),
        pro_rata_share=_extract_pro_rata(view),
        tax_recovery=tax,
        insurance_recovery=insurance,
        professional_review_flags=review_flags,
    )


def _number(name: str, value: object, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        qualifier = "positive" if not allow_zero else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return result


def _cost_values(name: str, raw: object) -> dict[str, float]:
    if isinstance(raw, Mapping):
        aliases = {
            "current": ("current", "amount", "cost"),
            "base": ("base", "base_year"),
            "prior": ("prior", "previous", "prior_year"),
            "years_elapsed": ("years_elapsed", "years", "lease_years_elapsed"),
            "occupancy_pct": ("occupancy_pct", "actual_occupancy_pct", "occupancy"),
            "variable": ("variable", "variable_cost", "variable_expenses"),
        }
        result: dict[str, float] = {}
        for target, keys in aliases.items():
            for key in keys:
                if key in raw and raw[key] is not None:
                    result[target] = _number(f"annual_costs.{name}.{key}", raw[key])
                    break
        return result
    if raw is None:
        return {}
    return {"current": _number(f"annual_costs.{name}", raw)}


def _claim_payload(claim: CitedClaim) -> dict[str, object]:
    return asdict(claim)


def _flag(issue: str, claim: CitedClaim | None = None) -> dict[str, object]:
    result: dict[str, object] = {"issue": issue, "review": "professional"}
    if claim is not None and claim.status != "missing":
        result["clause"] = _claim_payload(claim)
    return result


def _share(
    terms: RecoveryTerms,
    tenant_sf: float | int | None,
    total_sf: float | int | None,
) -> tuple[float | None, str, list[str], list[str], list[dict[str, object]]]:
    basis: list[str] = []
    missing: list[str] = []
    flags: list[dict[str, object]] = []
    status = "missing"
    stated: float | None = None
    formula: float | None = None
    if terms.pro_rata_share.stated_pct.status != "missing":
        stated = _number("stated pro-rata share", terms.pro_rata_share.stated_pct.value)
        if stated > 1:
            raise ValueError("stated pro-rata share must be a decimal fraction between 0 and 1")
        basis.append("stated pro-rata percentage")
        status = "stated"
    if terms.pro_rata_share.formula.status != "missing":
        formula_value = terms.pro_rata_share.formula.value
        if formula_value == "tenant_sf / total_sf":
            if tenant_sf is None:
                missing.append("tenant_sf")
            if total_sf is None:
                missing.append("total_sf")
            if tenant_sf is not None and total_sf is not None:
                tenant = _number("tenant_sf", tenant_sf)
                total = _number("total_sf", total_sf, allow_zero=False)
                if tenant > total:
                    flags.append(_flag("tenant_sf exceeds total_sf; allocation requires review", terms.pro_rata_share.formula))
                formula = tenant / total
                basis.append("tenant_sf / total_sf cited allocation formula")
                status = "inferred"
        else:
            missing.append("allocation_denominator_for_tenants_sharing_service")
    elif stated is None:
        if tenant_sf is None:
            missing.append("tenant_sf")
        if total_sf is None:
            missing.append("total_sf")
        if tenant_sf is not None and total_sf is not None:
            tenant = _number("tenant_sf", tenant_sf)
            total = _number("total_sf", total_sf, allow_zero=False)
            if tenant > total:
                flags.append(_flag("tenant_sf exceeds total_sf; allocation requires review"))
            formula = tenant / total
            status = "inferred"
            basis.append("derived from tenant_sf/total_sf (lease states no percentage)")
            flags.append(_flag(
                "confirm denominator definition: GLA vs GLA-occupied vs defined Center"
            ))
    if stated is not None and formula is not None and not math.isclose(stated, formula, rel_tol=0.02, abs_tol=0.0005):
        flags.append(_flag("stated share and supplied-area formula do not reconcile", terms.pro_rata_share.formula))
    return stated if stated is not None else formula, status, basis, sorted(set(missing)), flags


def _cam_ceiling(
    terms: RecoveryTerms,
    values: Mapping[str, float],
) -> tuple[float | None, list[str], list[str], list[dict[str, object]]]:
    current = values.get("current")
    if current is None:
        return None, [], ["annual_costs.cam.current"], []
    if terms.cam_cap.pct.status == "missing":
        return current, ["no cited CAM cap applied"], [], []

    pct = _number("CAM cap", terms.cam_cap.pct.value)
    mechanics = terms.cam_cap.cumulative_vs_noncumulative.value
    comparison = terms.cam_cap.over_base_vs_yoy.value
    basis: list[str] = []
    missing: list[str] = []
    flags: list[dict[str, object]] = []

    use_base = mechanics == "cumulative" or comparison == "over_base"
    use_prior = mechanics == "noncumulative" or comparison == "yoy"
    if use_base and use_prior:
        flags.append(_flag("CAM cap states conflicting base and year-over-year mechanics", terms.cam_cap.pct))
        return None, basis, ["unambiguous_cam_cap_mechanics"], flags
    if use_base:
        base = values.get("base")
        years = values.get("years_elapsed")
        if base is None:
            missing.append("annual_costs.cam.base")
        if years is None:
            missing.append("annual_costs.cam.years_elapsed")
        if missing:
            return None, basis, missing, flags
        assert base is not None and years is not None
        ceiling = base * ((1.0 + pct) ** years)
        basis.append("cumulative/over-base CAM ceiling = base × (1 + cap)^years_elapsed")
    elif use_prior:
        prior = values.get("prior")
        if prior is None:
            return None, basis, ["annual_costs.cam.prior"], flags
        ceiling = prior * (1.0 + pct)
        basis.append("noncumulative/year-over-year CAM ceiling = prior × (1 + cap)")
    else:
        flags.append(_flag("CAM cap percentage is stated but cumulative/base mechanics are ambiguous", terms.cam_cap.pct))
        return None, basis, ["unambiguous_cam_cap_mechanics"], flags
    return min(current, ceiling), basis, [], flags


def _gross_up_cam(
    terms: RecoveryTerms,
    values: Mapping[str, float],
    raw: object,
) -> tuple[dict[str, float] | None, list[str], list[str], list[dict[str, object]]]:
    current = values.get("current")
    if current is None:
        return None, [], ["annual_costs.cam.current"], []
    adjusted = dict(values)
    if terms.gross_up_pct.status == "missing":
        return adjusted, [], [], []
    if isinstance(raw, Mapping) and raw.get("already_grossed_up") is True:
        return adjusted, ["caller marked CAM pool as already grossed up"], [], []

    target = _number("gross-up occupancy", terms.gross_up_pct.value)
    if target > 1:
        raise ValueError("gross-up occupancy must be a decimal fraction between 0 and 1")
    occupancy = values.get("occupancy_pct")
    if occupancy is None:
        flag = _flag(
            "gross-up clause requires actual occupancy and variable-expense support",
            terms.gross_up_pct,
        )
        return None, [], ["annual_costs.cam.occupancy_pct"], [flag]
    if occupancy > 1:
        raise ValueError("annual_costs.cam.occupancy_pct must be a decimal fraction between 0 and 1")
    if occupancy >= target:
        return adjusted, ["actual occupancy meets or exceeds cited gross-up occupancy"], [], []
    variable = values.get("variable")
    if variable is None:
        flag = _flag(
            "gross-up below target occupancy requires the variable portion of CAM",
            terms.gross_up_pct,
        )
        return None, [], ["annual_costs.cam.variable"], [flag]
    if variable > current:
        raise ValueError("annual_costs.cam.variable cannot exceed annual_costs.cam.current")
    if occupancy == 0 and variable > 0:
        flag = _flag(
            "nonzero variable CAM cannot be grossed up from zero occupancy without a separate unit basis",
            terms.gross_up_pct,
        )
        return None, [], ["variable_cost_unit_basis_at_zero_occupancy"], [flag]
    fixed = current - variable
    adjusted["current"] = fixed + (variable * target / occupancy if variable else 0.0)
    return adjusted, [
        "grossed-up CAM = fixed cost + variable cost × cited target occupancy / actual occupancy"
    ], [], []


def _empty_line(name: str, missing: list[str], basis: list[str] | None = None) -> dict[str, object]:
    return {
        "line": name,
        "status": "not_computable",
        "annual_cost": None,
        "eligible_cost": None,
        "tenant_share": None,
        "admin_fee": None,
        "estimated_billing": None,
        "basis": basis or [],
        "limiting_clauses": [],
        "missing_inputs": sorted(set(missing)),
        "counsel_flags": [],
    }


def estimate_recoverable(
    terms: RecoveryTerms,
    annual_costs: Mapping[str, object],
    tenant_sf: float | int | None,
    total_sf: float | int | None,
) -> dict[str, object]:
    """Estimate annual tenant recovery billings from cited terms and cost pools.

    A cost value may be numeric or a mapping.  CAM caps accept ``current``,
    ``base``, ``prior``, and ``years_elapsed``.  A base-year tax stop accepts
    ``current`` and ``base``.  These extra inputs are required only when the
    cited clause needs them; they are never defaulted.
    """

    if not isinstance(terms, RecoveryTerms):
        raise TypeError("terms must be RecoveryTerms")
    if not isinstance(annual_costs, Mapping):
        raise TypeError("annual_costs must be a mapping")

    share, share_status, share_basis, share_missing, share_flags = _share(
        terms, tenant_sf, total_sf
    )
    base_flags = [*terms.professional_review_flags, *share_flags]
    flags = list(base_flags)
    costs = {
        name: _cost_values(name, annual_costs.get(name))
        for name in ("cam", "taxes", "insurance")
    }
    lines: dict[str, dict[str, object]] = {}

    # CAM
    if terms.cam_recovery.status == "missing":
        line = _empty_line("cam", ["cited_cam_recovery_clause"], share_basis)
    elif share is None:
        line = _empty_line("cam", share_missing or ["pro_rata_share"], share_basis)
    else:
        grossed_costs, gross_basis, gross_missing, gross_flags = _gross_up_cam(
            terms, costs["cam"], annual_costs.get("cam")
        )
        flags.extend(gross_flags)
        if grossed_costs is None:
            eligible = None
            cap_basis = []
            cap_missing = gross_missing
            cap_flags = gross_flags
        else:
            eligible, cap_basis, cap_missing, cap_flags = _cam_ceiling(terms, grossed_costs)
        flags.extend(cap_flags)
        if eligible is None:
            line = _empty_line("cam", cap_missing, share_basis + gross_basis + cap_basis)
            line["counsel_flags"] = [*base_flags, *gross_flags, *cap_flags]
        else:
            current = costs["cam"]["current"]
            subtotal = eligible * share
            admin = 0.0
            admin_basis = "no cited CAM administrative fee applied"
            limiting = [_claim_payload(terms.cam_recovery)]
            if terms.cam_cap.pct.status != "missing":
                limiting.append(_claim_payload(terms.cam_cap.pct))
            if terms.gross_up_pct.status != "missing":
                limiting.append(_claim_payload(terms.gross_up_pct))
            if terms.admin_fee_pct.status != "missing":
                fee = _number("CAM administrative fee", terms.admin_fee_pct.value)
                admin = subtotal * fee
                limiting.append(_claim_payload(terms.admin_fee_pct))
                admin_basis = (
                    "administrative fee applied at cited maximum to tenant CAM share; actual charged rate may be lower"
                    if _admin_fee_is_maximum(terms.admin_fee_pct)
                    else "administrative fee applied to tenant CAM share"
                )
            line = {
                "line": "cam",
                "status": "estimated",
                "annual_cost": round(current, 2),
                "eligible_cost": round(eligible, 2),
                "tenant_share": round(share, 8),
                "admin_fee": round(admin, 2),
                "estimated_billing": round(subtotal + admin, 2),
                "basis": share_basis + gross_basis + cap_basis + [
                    "caller-provided CAM pool is assumed screened against cited exclusions",
                    admin_basis,
                ],
                "limiting_clauses": limiting,
                "missing_inputs": [],
                "counsel_flags": [*base_flags, *gross_flags, *cap_flags],
            }
            if terms.exclusions:
                exclusion_flag = _flag(
                    "CAM ledger classification must be reviewed against cited exclusions",
                    terms.exclusions[0],
                )
                line["counsel_flags"] = [
                    *base_flags, *gross_flags, *cap_flags, exclusion_flag
                ]
                flags.append(exclusion_flag)
    lines["cam"] = line

    # Taxes
    tax_value = terms.tax_recovery.value
    if terms.tax_recovery.status == "missing":
        line = _empty_line("taxes", ["cited_tax_recovery_clause"], share_basis)
    elif share is None:
        line = _empty_line("taxes", share_missing or ["pro_rata_share"], share_basis)
    else:
        current = costs["taxes"].get("current")
        missing: list[str] = []
        if current is None:
            missing.append("annual_costs.taxes.current")
        base = costs["taxes"].get("base")
        if tax_value == "base_year_stop" and base is None:
            missing.append("annual_costs.taxes.base")
        if missing:
            line = _empty_line("taxes", missing, share_basis)
        else:
            assert current is not None
            eligible = max(0.0, current - base) if tax_value == "base_year_stop" and base is not None else current
            basis = share_basis + (["current taxes less caller-provided base-year taxes"] if tax_value == "base_year_stop" else ["current tax pool × pro-rata share"])
            line = {
                "line": "taxes",
                "status": "estimated",
                "annual_cost": round(current, 2),
                "eligible_cost": round(eligible, 2),
                "tenant_share": round(share, 8),
                "admin_fee": 0.0,
                "estimated_billing": round(eligible * share, 2),
                "basis": basis,
                "limiting_clauses": [_claim_payload(terms.tax_recovery)],
                "missing_inputs": [],
                "counsel_flags": [],
            }
            line["counsel_flags"] = list(base_flags)
    lines["taxes"] = line

    # Insurance
    if terms.insurance_recovery.status == "missing":
        line = _empty_line("insurance", ["cited_insurance_recovery_clause"], share_basis)
    elif share is None:
        line = _empty_line("insurance", share_missing or ["pro_rata_share"], share_basis)
    else:
        current = costs["insurance"].get("current")
        if current is None:
            line = _empty_line("insurance", ["annual_costs.insurance.current"], share_basis)
        else:
            line_flags: list[dict[str, object]] = []
            if terms.insurance_recovery.value == "included_in_cam":
                duplicate = _flag(
                    "insurance is included in CAM; confirm CAM and insurance inputs do not double count",
                    terms.insurance_recovery,
                )
                line_flags.append(duplicate)
                flags.append(duplicate)
            line = {
                "line": "insurance",
                "status": "estimated",
                "annual_cost": round(current, 2),
                "eligible_cost": round(current, 2),
                "tenant_share": round(share, 8),
                "admin_fee": 0.0,
                "estimated_billing": round(current * share, 2),
                "basis": share_basis + ["caller-provided insurance pool × pro-rata share"],
                "limiting_clauses": [_claim_payload(terms.insurance_recovery)],
                "missing_inputs": [],
                "counsel_flags": line_flags,
            }
            line["counsel_flags"] = [*base_flags, *line_flags]
    lines["insurance"] = line

    computed = [
        float(line["estimated_billing"])
        for line in lines.values()
        if line["status"] == "estimated" and line["estimated_billing"] is not None
    ]
    incomplete = [name for name, line in lines.items() if line["status"] != "estimated"]
    subtotal = round(sum(computed), 2)
    total = None if incomplete else subtotal
    unique_flags: list[dict[str, object]] = []
    seen_issues: set[str] = set()
    for flag in flags:
        issue = str(flag["issue"])
        if issue not in seen_issues:
            unique_flags.append(flag)
            seen_issues.add(issue)
    return {
        "status": "estimated" if not incomplete else ("partial" if computed else "not_computable"),
        "pro_rata_share": round(share, 8) if share is not None else None,
        "pro_rata_share_status": share_status,
        "pro_rata_share_basis": share_basis,
        "lines": lines,
        "computed_subtotal": subtotal if computed else None,
        "total_estimated_billing": total,
        "tenant_billing_estimate": total,
        "missing_lines": incomplete,
        "basis": "annual estimate from caller-provided cost pools and cited lease allocation terms",
        "counsel_flags": unique_flags,
        "professional_review_flags": unique_flags,
    }


__all__ = [
    "CAMCap",
    "AuditRight",
    "ProRataShare",
    "RecoveryTerms",
    "extract_recovery_terms",
    "estimate_recoverable",
]
