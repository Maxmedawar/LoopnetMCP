"""Deterministic, section-aware extraction of commercial-lease clauses.

This module uses targeted regular expressions over bounded clause windows.  It
does not call an LLM and it does not complete blanks from market convention.
Every positive extraction retains a verbatim substring of the sanitized source;
anything not supported by that evidence remains an explicit missing claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from cre_mcp.leases.models import (
    CitedClaim,
    DefaultCurePeriod,
    Escalations,
    InsuranceRequirement,
    LeaseAbstract,
    LeaseDates,
    LeaseOption,
    Parties,
    Premises,
    RecoveryStructure,
    RentPeriod,
    Restrictions,
    Security,
)
from cre_mcp.truth.sanitize import sanitize_text

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    "Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    "Nov(?:ember)?|Dec(?:ember)?"
)
_DATE = rf"(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?\s*,?\s+\d{{4}}|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}"
_MONEY = r"(?:\$\s*)?(?:-\s*0\s*-|\d[\d,]*(?:\.\d{1,2})?)"
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}


@dataclass(frozen=True)
class _Section:
    heading: str
    start: int
    end: int


class _SearchText:
    """Whitespace-compacted search view mapped back to exact source offsets."""

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
        self.sections = _sections(source)

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.offsets:
            return 0, 0
        start = min(max(start, 0), len(self.offsets) - 1)
        if end <= start:
            return self.offsets[start], self.offsets[start] + 1
        end = min(end - 1, len(self.offsets) - 1)
        return self.offsets[start], self.offsets[end] + 1

    def locator(self, compact_offset: int) -> str:
        original, _ = self.original_span(compact_offset, compact_offset + 1)
        for section in self.sections:
            if section.start <= original < section.end:
                return section.heading
        return f"chars {original}-{original + 1}"

    def quote(self, start: int, end: int) -> str:
        raw_start, raw_end = self.original_span(start, end)
        if raw_end - raw_start > 200:
            center = (raw_start + raw_end) // 2
            raw_start = max(raw_start, center - 99)
            raw_end = min(len(self.source), raw_start + 200)
        return self.source[raw_start:raw_end].strip()[:200]

    def claim(
        self,
        value: object,
        start: int,
        end: int,
        *,
        confidence: float,
        status: str = "stated",
    ) -> CitedClaim:
        quote = self.quote(start, end)
        if status == "inferred":
            return CitedClaim.inferred(
                value, quote=quote, locator=self.locator(start), confidence=confidence
            )
        return CitedClaim.stated(
            value, quote=quote, locator=self.locator(start), confidence=confidence
        )


def _sections(text: str) -> list[_Section]:
    candidates: list[tuple[str, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = " ".join(line.strip().split())
        if 2 <= len(stripped) <= 110 and (
            re.match(r"^(?:[A-Z]|\d{1,2})[.)]\s+[A-Z]", stripped)
            or (stripped.isupper() and any(c.isalpha() for c in stripped))
        ):
            candidates.append((stripped.rstrip(":"), offset + line.find(line.lstrip())))
        offset += len(line)
    sections: list[_Section] = []
    for index, (heading, start) in enumerate(candidates):
        end = candidates[index + 1][1] if index + 1 < len(candidates) else len(text)
        sections.append(_Section(heading[:100], start, end))
    return sections


def _parse_money(raw: str) -> float | None:
    cleaned = raw.replace("$", "").replace(" ", "").replace("*", "").strip()
    if re.fullmatch(r"-?0-?", cleaned):
        return 0.0
    # SEC exhibits occasionally use a final comma as the decimal separator
    # (e.g. 40,000,00).  Normalize only when the final group has two digits.
    if "." not in cleaned and "," in cleaned and len(cleaned.rsplit(",", 1)[1]) == 2:
        head, decimals = cleaned.rsplit(",", 1)
        cleaned = head.replace(",", "") + "." + decimals
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_pct(raw: str) -> float | None:
    try:
        return float(raw.replace("%", "").replace(",", ".").strip()) / 100.0
    except ValueError:
        return None


def _normalize_date(raw: str) -> str:
    cleaned = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", raw.strip(), flags=re.I)
    for fmt in (
        "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
        "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y",
    ):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return raw.strip()


def _number(raw: str | None) -> int | None:
    if not raw:
        return None
    paren = re.search(r"\((\d+)\)", raw)
    if paren:
        return int(paren.group(1))
    digit = re.search(r"\d+", raw)
    if digit:
        return int(digit.group(0))
    return _NUMBER_WORDS.get(raw.strip().casefold())


def _clean_party(raw: str) -> str:
    value = " ".join(raw.split()).strip(" ,.;")
    value = re.split(r",?\s+whose\s+address\b", value, maxsplit=1, flags=re.I)[0]
    value = re.split(
        r",?\s+(?:a|an)\s+(?:(?:Virginia|Delaware|Maryland|New York|California)\s+)?"
        r"(?:corporation|limited|general partnership|company|bank)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    return value.strip(" ,.;")


def _extract_parties(view: _SearchText) -> Parties:
    parties = Parties()
    intro = re.search(
        r"(?:by\s+(?:and|&)\s+between|between)\s+(?P<ll>.{2,550}?)\s*"
        r"\((?:[^)]{0,100}?)(?:landlord)(?:[^)]{0,50}?)\)\s*,?\s*"
        r"(?:and|&)\s+(?P<tt>.{2,550}?)\s*"
        r"\((?:[^)]{0,100}?)(?:tenant)(?:[^)]{0,50}?)\)",
        view.text,
        re.I,
    )
    if intro:
        parties.landlord = view.claim(
            _clean_party(intro.group("ll")), *intro.span("ll"), confidence=0.96
        )
        parties.tenant = view.claim(
            _clean_party(intro.group("tt")), *intro.span("tt"), confidence=0.96
        )
    else:
        ll = re.search(r"\bLANDLORD\s*:\s*(?P<v>.{2,350}?)(?=\s+TENANT\s*:)", view.text, re.I)
        tt = re.search(r"\bTENANT\s*:\s*(?P<v>.{2,250}?)(?=\s+(?:EXISTING|PREMISES|DATE|LEASE)\b)", view.text, re.I)
        if ll:
            parties.landlord = view.claim(_clean_party(ll.group("v")), *ll.span("v"), confidence=0.93)
        if tt:
            parties.tenant = view.claim(_clean_party(tt.group("v")), *tt.span("v"), confidence=0.93)

    guarantor = re.search(
        r"\b(?:GUARANTOR|GUARANTY\s+BY)\s*:\s*(?P<v>[A-Z][A-Za-z0-9&.,' -]{2,120})",
        view.text,
        re.I,
    )
    if guarantor:
        parties.guarantor = view.claim(
            _clean_party(guarantor.group("v")), *guarantor.span("v"), confidence=0.88
        )
    return parties


def _extract_premises(view: _SearchText) -> Premises:
    premises = Premises()
    address_pattern = re.compile(
        r"\b\d{2,6}\s+(?:[A-Za-z][A-Za-z0-9.'-]*\s+){1,8}"
        r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Boulevard|Blvd\.?|"
        r"Highway|Hwy\.?|Parkway|Pkwy\.?|Lane|Ln\.?|Court|Ct\.?|Way)\b"
        r"(?:\s*,?\s*[A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?",
    )
    address = next(
        (
            candidate for candidate in address_pattern.finditer(view.text)
            if re.search(
                r"(?:\bBuilding\b.{0,80}\blocated\s+at\b|\bPremises\b.{0,100}"
                r"(?:\baddress\b|\blocated\b)|\bPremises\s+Address\b|"
                r"\(\s*(?:the\s+)?[\"“]?Building[\"”]?\s*\))",
                view.text[max(0, candidate.start() - 140):min(len(view.text), candidate.end() + 140)],
                re.I,
            )
            and not re.search(
                r"(?:ACKNOWLEDG(?:E)?MENT|notary|whose\s+address|address\s+for\s+notices?|"
                r"Real\s+Estate\s+Department).{0,120}$",
                view.text[max(0, candidate.start() - 220):candidate.start()], re.I,
            )
        ),
        None,
    )
    if address is not None:
        premises.address = view.claim(address.group(0).strip(), *address.span(), confidence=0.88)

    suite = re.search(r"\b(?:Suite|Unit)\s*#?\s*(?P<v>[A-Z0-9][A-Z0-9.-]{0,15})\b", view.text, re.I)
    if suite:
        premises.suite = view.claim(suite.group("v"), *suite.span("v"), confidence=0.86)

    sf_patterns = (
        r"(?:approximately|approximate(?:ly)?(?:\s+total)?)\s+(?:rentable\s+area\s+(?:of\s+)?)?"
        r"(?P<v>\d[\d,]*(?:\.\d+)?)\s+rentable\s+square\s+feet",
        r"(?:approximately|approximate(?:ly)?(?:\s+total)?)\s+square\s+footage\s+of\s+"
        r"(?P<v>\d[\d,]*(?:\.\d+)?)\s+square\s+feet",
        r"(?P<v>\d[\d,]*(?:\.\d+)?)\s+rentable\s+square\s+feet\s+(?:of|consisting)",
    )
    for pattern in sf_patterns:
        match = re.search(pattern, view.text, re.I)
        if match:
            value = _parse_money(match.group("v"))
            if value is not None:
                premises.rentable_sf = view.claim(value, *match.span("v"), confidence=0.9)
                break
    return premises


def _extract_dates(view: _SearchText) -> LeaseDates:
    dates = LeaseDates()
    term_sentence = re.search(
        rf"(?:term|extension\s+term)[^.\n]{{0,180}}?(?:shall\s+)?commence\s+on\s+"
        rf"(?P<start>{_DATE})[^.\n]{{0,180}}?(?:expire|expires|terminate|terminates)\s+on\s+"
        rf"(?P<end>{_DATE})",
        view.text,
        re.I,
    )
    if term_sentence:
        dates.commencement = view.claim(
            _normalize_date(term_sentence.group("start")), *term_sentence.span("start"), confidence=0.96
        )
        dates.expiration = view.claim(
            _normalize_date(term_sentence.group("end")), *term_sentence.span("end"), confidence=0.96
        )
    else:
        conditional = re.search(
            r"term\s+of\s+this\s+Lease\s+shall\s+commence\s+upon\s+(?P<v>(?:the\s+)?"
            r"(?:earlier|later)\s+of\s*:.{20,650}?)\s*,?\s*such\s+date\s+being\s+"
            r"(?:hereinafter\s+called\s+)?the\s+Commencement\s+Date",
            view.text,
            re.I,
        )
        explicit = re.search(
            rf"(?:Commencement\s+Date)[^.\n]{{0,100}}?(?:shall\s+be|is(?:\s+hereby)?\s+"
            rf"(?:amended|changed)\s+to|is|:|commence\s+on)\s+"
            rf"(?P<v>{_DATE})",
            view.text,
            re.I,
        )
        reverse = re.search(rf"(?P<v>{_DATE})\s*\([^)]{{0,90}}Commencement\s+Date[^)]*\)", view.text, re.I)
        if conditional:
            value = " ".join(conditional.group("v").split())
            dates.commencement = view.claim(value, *conditional.span("v"), confidence=0.85)
        elif explicit or reverse:
            match = explicit or reverse
            assert match is not None
            dates.commencement = view.claim(
                _normalize_date(match.group("v")), *match.span("v"), confidence=0.92
            )

        expiration = re.search(
            rf"(?:Expiration\s+Date)[^.\n]{{0,100}}?(?:shall\s+be|is(?:\s+hereby)?\s+"
            rf"(?:amended|extended|changed)\s+(?:to|through)|is|:)\s+(?P<v>{_DATE})",
            view.text,
            re.I,
        ) or re.search(
            rf"(?:term\s+of\s+(?:this|the)\s+Lease|the\s+Lease\s+term|this\s+Lease)"
            rf"[^.\n]{{0,180}}?(?:expire|expires|expiring|terminate|terminating)\s+on\s+"
            rf"(?P<v>{_DATE})",
            view.text,
            re.I,
        )
        if expiration:
            dates.expiration = view.claim(
                _normalize_date(expiration.group("v")), *expiration.span("v"), confidence=0.92
            )
        else:
            reference = re.search(
                r"(?:expire|expires|expiring)\s+on\s+(?P<v>the\s+Lease\s+Expiration\s+Date"
                r"[^,.;]{0,100})",
                view.text,
                re.I,
            )
            if reference:
                dates.expiration = view.claim(
                    " ".join(reference.group("v").split()), *reference.span("v"), confidence=0.76
                )

    duration = re.search(
        r"(?:term|extension\s+term)[^.]{0,180}?(?:period\s+of\s+)?"
        r"(?P<years>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s+years?"
        r"(?:\s+and\s+(?P<months>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s+months?)?",
        view.text,
        re.I,
    )
    if duration:
        years = _number(duration.group("years"))
        months = _number(duration.group("months")) or 0
        if years is not None:
            dates.term_months = view.claim(
                years * 12 + months, *duration.span(), confidence=0.9
            )
    return dates


def _amount_matches(text: str, *, base: int = 0) -> Iterable[tuple[float, int, int]]:
    pattern = re.compile(r"(?:\$\s*)?(?:-\s*0\s*-|\d[\d,]*(?:[.,]\d{2}))")
    for match in pattern.finditer(text):
        value = _parse_money(match.group(0))
        if value is not None:
            yield value, base + match.start(), base + match.end()


def _rent_rows(view: _SearchText) -> list[RentPeriod]:
    rows: list[RentPeriod] = []
    row_pattern = re.compile(
        rf"(?P<start>{_DATE})\s*(?:-|–|—|through|to)\s*(?P<end>{_DATE})\s+"
        rf"(?P<annual>{_MONEY})\s*(?:\*|\(\s*annualized\s+amount\s*\))*\s+"
        rf"(?P<monthly>{_MONEY})\s+(?P<psf>{_MONEY})",
        re.I,
    )
    seen: set[tuple[object, ...]] = set()
    for match in row_pattern.finditer(view.text):
        annual = _parse_money(match.group("annual"))
        monthly = _parse_money(match.group("monthly"))
        psf = _parse_money(match.group("psf"))
        key = (match.group("start"), match.group("end"), annual, monthly, psf)
        if key in seen or annual is None:
            continue
        seen.add(key)
        row = RentPeriod(
            start=view.claim(_normalize_date(match.group("start")), *match.span("start"), confidence=0.94),
            end=view.claim(_normalize_date(match.group("end")), *match.span("end"), confidence=0.94),
            annual=view.claim(annual, *match.span("annual"), confidence=0.94),
            label=view.claim(
                f"{match.group('start')} through {match.group('end')}", *match.span(), confidence=0.9
            ),
        )
        if monthly is not None:
            row.monthly = view.claim(monthly, *match.span("monthly"), confidence=0.94)
        if psf is not None:
            row.psf = view.claim(psf, *match.span("psf"), confidence=0.94)
        rows.append(row)

    # Basic-provisions tables in older exhibits often arrange labels, PSF, and
    # annual rent as vertical columns rather than one row per period.
    basic = re.search(
        r"\b(?:Minimum|Base)\s+Rent\b(?P<body>.{0,2200}?)\bPercentage\s+Rent\b",
        view.text,
        re.I,
    )
    if basic and not rows:
        body = basic.group("body")
        body_start = basic.start("body")
        psf_marker = re.search(r"\bPer\s+(?:Sq\.?\s*Ft\.?|Rentable\s+Square\s+Foot)\b", body, re.I)
        annual_marker = re.search(r"\bPer\s+Annum\b", body, re.I)
        if psf_marker and annual_marker and psf_marker.end() < annual_marker.start():
            psfs = list(_amount_matches(body[psf_marker.end():annual_marker.start()], base=body_start + psf_marker.end()))
            annuals = list(_amount_matches(body[annual_marker.end():], base=body_start + annual_marker.end()))
            # Party addresses and ZIP codes do not have decimal cents, so the
            # amount matcher naturally ignores them.  Bound to plausible table
            # width to avoid reading later prose figures.
            count = min(len(psfs), len(annuals), 20)
            labels = ["Original Term"] + [f"Option {i}" for i in range(1, count)]
            for index in range(count):
                annual, a_start, a_end = annuals[index]
                psf, p_start, p_end = psfs[index]
                label_quote_start = basic.start()
                row = RentPeriod(
                    annual=view.claim(annual, a_start, a_end, confidence=0.82),
                    monthly=view.claim(
                        round(annual / 12.0, 2), a_start, a_end,
                        confidence=0.72, status="inferred",
                    ),
                    psf=view.claim(psf, p_start, p_end, confidence=0.82),
                    label=view.claim(
                        labels[index], label_quote_start, min(label_quote_start + 80, len(view.text)),
                        confidence=0.72,
                    ),
                )
                rows.append(row)
    return rows


def _extract_escalations(view: _SearchText, rents: list[RentPeriod]) -> Escalations:
    escalations = Escalations()
    amounts = [p.annual.value for p in rents if p.annual.status != "missing"]
    if len(amounts) >= 2:
        first = rents[0].annual
        escalations.fixed_steps = CitedClaim.stated(
            len(set(amounts)) > 1,
            quote=first.quote,
            locator=first.locator,
            confidence=min(first.confidence, 0.88),
        )

    cpi = re.search(r"\b(?:Consumer\s+Price\s+Index|CPI(?:-U|-W)?)\b", view.text, re.I)
    if cpi:
        escalations.cpi_index = view.claim(cpi.group(0), *cpi.span(), confidence=0.86)
        window_start, window_end = max(0, cpi.start() - 250), min(len(view.text), cpi.end() + 650)
        window = view.text[window_start:window_end]
        cap = re.search(r"(?:cap|not\s+exceed|maximum)[^%]{0,100}?(?P<v>\d+(?:\.\d+)?)\s*%", window, re.I)
        floor = re.search(r"(?:floor|not\s+less\s+than|minimum)[^%]{0,100}?(?P<v>\d+(?:\.\d+)?)\s*%", window, re.I)
        if cap:
            escalations.cpi_cap_pct = view.claim(
                _parse_pct(cap.group("v") + "%"),
                window_start + cap.start("v"), window_start + cap.end("v"), confidence=0.8,
            )
        if floor:
            escalations.cpi_floor_pct = view.claim(
                _parse_pct(floor.group("v") + "%"),
                window_start + floor.start("v"), window_start + floor.end("v"), confidence=0.8,
            )
        annual = re.search(r"\b(?:annual(?:ly)?|each\s+year)\b", window, re.I)
        if annual:
            escalations.cpi_frequency_months = view.claim(
                12, window_start + annual.start(), window_start + annual.end(), confidence=0.72
            )

    pct = re.search(r"\bPercentage\s+Rent\b", view.text, re.I)
    if pct:
        escalations.percentage_rent = view.claim(True, *pct.span(), confidence=0.92)
        window_end = min(len(view.text), pct.end() + 1200)
        window = view.text[pct.end():window_end]
        pair = re.search(
            r"(?P<bp>\$?\s*\d[\d,]*(?:\.\d{2})?)\s+(?P<rate>\d+(?:\.\d+)?\s*%)",
            window,
        )
        if pair:
            breakpoint = _parse_money(pair.group("bp"))
            rate = _parse_pct(pair.group("rate"))
            if breakpoint is not None:
                escalations.percentage_breakpoint = view.claim(
                    breakpoint, pct.end() + pair.start("bp"), pct.end() + pair.end("bp"), confidence=0.9
                )
            if rate is not None:
                escalations.percentage_rate = view.claim(
                    rate, pct.end() + pair.start("rate"), pct.end() + pair.end("rate"), confidence=0.9
                )
            escalations.percentage_breakpoint_type = view.claim(
                "stated", pct.end() + pair.start(), pct.end() + pair.end(), confidence=0.88
            )
        else:
            rate_match = re.search(r"(?:Percentage\s+Rent\s+Rate|percentage\s+rate)[^%]{0,100}?(?P<v>\d+(?:\.\d+)?)\s*%", window, re.I)
            bp_match = re.search(r"(?:breakpoint)[^$\d]{0,80}(?P<v>\$?\s*\d[\d,]*(?:\.\d{2})?)", window, re.I)
            if rate_match:
                escalations.percentage_rate = view.claim(
                    _parse_pct(rate_match.group("v") + "%"), pct.end() + rate_match.start("v"),
                    pct.end() + rate_match.end("v"), confidence=0.82,
                )
            if bp_match:
                value = _parse_money(bp_match.group("v"))
                if value is not None:
                    escalations.percentage_breakpoint = view.claim(
                        value, pct.end() + bp_match.start("v"), pct.end() + bp_match.end("v"), confidence=0.82
                    )
        natural = re.search(r"\bnatural\s+(?:percentage\s+rent\s+)?breakpoint\b", window, re.I)
        if natural:
            escalations.percentage_breakpoint_type = view.claim(
                "natural", pct.end() + natural.start(), pct.end() + natural.end(), confidence=0.9
            )
    return escalations


def _presence_claim(view: _SearchText, patterns: Iterable[str], *, confidence: float = 0.84) -> CitedClaim:
    for pattern in patterns:
        match = re.search(pattern, view.text, re.I)
        if match:
            return view.claim(True, *match.span(), confidence=confidence)
    return CitedClaim.missing()


def _extract_recovery(view: _SearchText) -> RecoveryStructure:
    recovery = RecoveryStructure()
    types = (
        ("nnn", r"\b(?:triple\s+net|NNN)\b"),
        ("modified-gross", r"\bmodified\s+gross\b"),
        ("gross", r"\b(?:full[- ]service\s+gross|gross\s+lease)\b"),
    )
    for value, pattern in types:
        match = re.search(pattern, view.text, re.I)
        if match:
            recovery.lease_type = view.claim(value, *match.span(), confidence=0.9)
            break
    recovery.cam_recovery = _presence_claim(view, (
        r"Tenant\s+shall\s+pay.{0,220}?(?:Common\s+Area(?:\s+Maintenance|\s+Charge)?|CAM)\b",
        r"Estimated\s+Operating\s+Charges.{0,160}?\bCAM\b",
    ), confidence=0.9)
    recovery.tax_recovery = _presence_claim(view, (
        r"Tenant\s+shall\s+pay.{0,180}?(?:real\s+estate\s+tax(?:es)?|Tax\s+Expenses)\b",
        r"Estimated\s+Operating\s+Charges.{0,180}?\bTaxes\b",
    ))
    recovery.insurance_recovery = _presence_claim(view, (
        r"Tenant\s+shall\s+pay.{0,180}?(?:insurance\s+(?:costs|premiums|expenses)|Insurance\s+Expenses)\b",
        r"Estimated\s+Operating\s+Charges.{0,220}?\bInsurance\b",
    ))
    cap = re.search(
        r"(?:increases?\s+for\s+)?(?:Charges?\s+for\s+)?(?:Common\s+Area\s+Maintenance|CAM)"
        r"[^%]{0,180}?(?:not\s+exceed|cap(?:ped)?(?:\s+at)?)[^%]{0,80}?"
        r"(?P<v>\d+(?:\.\d+)?)\s*%",
        view.text,
        re.I,
    )
    if cap:
        recovery.cam_cap_pct = view.claim(
            _parse_pct(cap.group("v") + "%"), *cap.span("v"), confidence=0.88
        )
    base_year = re.search(
        r"\bBase\s+Year\s+(?:for\s+(?:Taxes|Expenses)\s+)?(?:shall\s+be|is|:)\s*"
        r"(?P<v>(?:calendar\s+year\s+)?\d{4})",
        view.text,
        re.I,
    )
    if base_year:
        year = int(re.search(r"\d{4}", base_year.group("v")).group(0))  # type: ignore[union-attr]
        recovery.base_year = view.claim(year, *base_year.span("v"), confidence=0.9)
    admin = re.search(
        r"administrative?\s+(?:costs?|fee)[^%]{0,100}?(?P<v>\d+(?:\.\d+)?)\s*%",
        view.text,
        re.I,
    )
    if admin:
        recovery.admin_fee_pct = view.claim(
            _parse_pct(admin.group("v") + "%"), *admin.span("v"), confidence=0.86
        )
    gross_up = re.search(
        r"gross(?:ed)?[- ]up[^%]{0,140}?(?P<v>\d+(?:\.\d+)?)\s*%",
        view.text,
        re.I,
    )
    if gross_up:
        recovery.gross_up_pct = view.claim(
            _parse_pct(gross_up.group("v") + "%"), *gross_up.span("v"), confidence=0.84
        )
    return recovery


def _option_type(text: str) -> str:
    low = text.casefold()
    if "first refusal" in low or "rofr" in low:
        return "rofr"
    if "first offer" in low or "rofo" in low:
        return "rofo"
    if "purchas" in low:
        return "purchase"
    if "terminat" in low:
        return "terminate"
    if "expan" in low:
        return "expand"
    if "extend" in low or "extension" in low:
        return "extend"
    return "renew"


def _extract_options(view: _SearchText) -> list[LeaseOption]:
    heading = re.compile(
        r"\b(?:Option\s+to\s+(?:Renew|Extend|Terminate|Expand|Purchase)|"
        r"(?:Renewal|Extension|Termination|Expansion|Purchase)\s+Option|"
        r"Right\s+of\s+First\s+(?:Refusal|Offer)|ROFR|ROFO)\b",
        re.I,
    )
    options: list[LeaseOption] = []
    seen: set[tuple[str, str]] = set()
    for match in heading.finditer(view.text):
        end = min(len(view.text), match.start() + 1600)
        next_section = re.search(r"\s+\d{1,2}\.\s+[A-Z][A-Za-z ]{2,45}[.:]", view.text[match.end():end])
        if next_section:
            end = match.end() + next_section.start()
        clause = view.text[match.start():end]
        if not re.search(r"\b(?:exercise|notice|grants?|right|option)\b", clause, re.I):
            continue
        kind = _option_type(match.group(0))
        notice = re.search(
            r"(?:exercise[ds]?|exercising)[^.]{0,180}?(?:written\s+)?notice[^.]{0,260}",
            clause,
            re.I,
        ) or re.search(
            r"(?:written\s+)?notice[^.]{0,180}?(?:not\s+(?:less|more)\s+than|prior\s+to)[^.]{0,180}",
            clause,
            re.I,
        )
        notice_value = ""
        if notice:
            notice_value = " ".join(notice.group(0).split()).strip(" ,;")
        key = (kind, notice_value)
        if key in seen:
            continue
        seen.add(key)
        option = LeaseOption(
            option_type=view.claim(kind, *match.span(), confidence=0.9),
        )
        if notice:
            n_start, n_end = match.start() + notice.start(), match.start() + notice.end()
            option.exercise_window = view.claim(notice_value, n_start, n_end, confidence=0.86)
            option.notice_deadline_rule = view.claim(notice_value, n_start, n_end, confidence=0.86)
        rent_basis = re.search(
            r"[^.]{0,100}(?:Minimum\s+Rent|Base\s+Rent|fair\s+market\s+rent|"
            r"market\s+rent|then[- ]prevailing\s+rent)[^.]{0,220}",
            clause,
            re.I,
        )
        if rent_basis:
            value = " ".join(rent_basis.group(0).split()).strip(" ,;")
            option.rent_basis = view.claim(
                value, match.start() + rent_basis.start(), match.start() + rent_basis.end(), confidence=0.8
            )
        options.append(option)
        if len(options) >= 20:
            break
    return options


def _labeled_clause(view: _SearchText, label: str, *, max_chars: int = 500) -> CitedClaim:
    match = re.search(
        rf"\b{label}\b\s*:?\s*(?P<v>.{{1,{max_chars}}}?)(?=\s+(?:\d{{1,2}}|[A-Z])[.)]\s+[A-Z]|$)",
        view.text,
        re.I,
    )
    if not match:
        return CitedClaim.missing()
    value = " ".join(match.group("v").split()).strip(" .")
    return view.claim(value, *match.span("v"), confidence=0.8)


def _sentence_clause(view: _SearchText, pattern: str) -> CitedClaim:
    match = re.search(rf"[^.]{{0,180}}\b(?:{pattern})\b[^.]{{0,280}}\.", view.text, re.I)
    if not match:
        return CitedClaim.missing()
    return view.claim(" ".join(match.group(0).split()), *match.span(), confidence=0.76)


def _extract_restrictions(view: _SearchText) -> Restrictions:
    restrictions = Restrictions()
    permitted = re.search(
        r"\bPermitted\s+Use\b\s*:?\s*(?P<v>.{1,700}?)(?=\s+\d{1,2}\.\s+[A-Z]|\s+[A-Z]\.\s+[A-Z])",
        view.text,
        re.I,
    )
    if permitted:
        restrictions.permitted_use = view.claim(
            " ".join(permitted.group("v").split()).strip(" ."), *permitted.span("v"), confidence=0.86
        )
    restrictions.exclusive_use = _sentence_clause(view, r"exclusive\s+(?:use|right)")
    restrictions.radius = _labeled_clause(view, r"Radius\s+Restriction", max_chars=180)
    restrictions.co_tenancy = _sentence_clause(view, r"co[- ]tenancy")
    restrictions.go_dark = _sentence_clause(view, r"go[- ]dark|cease\s+(?:continuous\s+)?operations")
    restrictions.continuous_operation = _sentence_clause(view, r"continuous(?:ly)?\s+(?:operation|operate|open)")
    restrictions.assignment_subletting_consent = _sentence_clause(
        view,
        r"(?:assign(?:ment)?|sublet(?:ting)?)[^.]{0,120}(?:consent|approval)",
    )
    return restrictions


def _extract_security(view: _SearchText) -> Security:
    security = Security()
    deposit = re.search(
        rf"\bSecurity\s+Deposit\b\s*:?\s*(?P<v>None|No\s+Deposit|{_MONEY})",
        view.text,
        re.I,
    )
    if deposit:
        raw = deposit.group("v")
        value = 0.0 if re.match(r"None|No", raw, re.I) else _parse_money(raw)
        if value is not None:
            security.deposit = view.claim(value, *deposit.span("v"), confidence=0.92)
    loc = re.search(
        rf"\b(?:letter\s+of\s+credit|LOC)\b[^$\d]{{0,100}}(?P<v>{_MONEY})",
        view.text,
        re.I,
    )
    if loc:
        value = _parse_money(loc.group("v"))
        if value is not None:
            security.letter_of_credit = view.claim(value, *loc.span("v"), confidence=0.86)
    guaranty = re.search(
        r"\b(?P<v>(?:good[- ]guy|limited|full|personal|corporate)\s+guarant(?:y|ee))\b",
        view.text,
        re.I,
    )
    if guaranty:
        security.guaranty_type = view.claim(
            guaranty.group("v").casefold(), *guaranty.span("v"), confidence=0.86
        )
    return security


def _extract_insurance(view: _SearchText) -> list[InsuranceRequirement]:
    results: list[InsuranceRequirement] = []
    clauses = re.finditer(
        r"(?P<type>public\s+liability|commercial\s+general\s+liability|property\s+insurance|"
        r"business\s+interruption\s+insurance)[^.]{0,700}\.",
        view.text,
        re.I,
    )
    for match in clauses:
        clause = match.group(0)
        amounts = list(re.finditer(r"\$\s*\d[\d,]*(?:\.\d{2})?", clause))
        requirement = InsuranceRequirement(
            coverage_type=view.claim(match.group("type").casefold(), *match.span("type"), confidence=0.84),
            requirement=view.claim(" ".join(clause.split()), *match.span(), confidence=0.76),
        )
        if amounts:
            first = amounts[0]
            value = _parse_money(first.group(0))
            if value is not None:
                requirement.per_occurrence = view.claim(
                    value, match.start() + first.start(), match.start() + first.end(), confidence=0.84
                )
        if len(amounts) > 1:
            second = amounts[1]
            value = _parse_money(second.group(0))
            if value is not None:
                requirement.aggregate = view.claim(
                    value, match.start() + second.start(), match.start() + second.end(), confidence=0.8
                )
        results.append(requirement)
        if len(results) >= 8:
            break
    return results


def _extract_cure_periods(view: _SearchText) -> list[DefaultCurePeriod]:
    results: list[DefaultCurePeriod] = []
    pattern = re.compile(
        r"(?P<clause>[^.]{0,180}\b(?:default|failure\s+to\s+pay|breach)\b[^.]{0,300}?"
        r"(?:within|period\s+of|for)\s+(?P<days>[A-Za-z]+(?:\s*\(\d+\))?|\d+)\s+days?"
        r"[^.]{0,180}\.)",
        re.I,
    )
    for match in pattern.finditer(view.text):
        days = _number(match.group("days"))
        if days is None or not 0 <= days <= 365:
            continue
        clause = match.group("clause")
        kind = "monetary" if re.search(r"rent|pay(?:ment)?|money", clause, re.I) else "nonmonetary"
        notice = bool(re.search(r"notice", clause, re.I))
        results.append(DefaultCurePeriod(
            default_type=view.claim(kind, *match.span("clause"), confidence=0.74, status="inferred"),
            cure_days=view.claim(days, *match.span("days"), confidence=0.84),
            notice_required=view.claim(notice, *match.span("clause"), confidence=0.76),
        ))
        if len(results) >= 12:
            break
    return results


def abstract_lease(text: str | object) -> LeaseAbstract:
    """Abstract sanitized commercial-lease text into cited standard fields.

    The function sanitizes defensively even when the reader already did so, so
    callers passing raw text receive the same injection posture as file callers.
    """
    if not isinstance(text, str):
        document_text = getattr(text, "text", None)
        if not isinstance(document_text, str):
            raise TypeError("text must be a string or an object with a string .text attribute")
        text = document_text
    sanitized = sanitize_text(text)
    view = _SearchText(sanitized.text)
    rents = _rent_rows(view)
    return LeaseAbstract(
        parties=_extract_parties(view),
        premises=_extract_premises(view),
        dates=_extract_dates(view),
        rent_schedule=rents,
        escalations=_extract_escalations(view, rents),
        recovery=_extract_recovery(view),
        options=_extract_options(view),
        security=_extract_security(view),
        restrictions=_extract_restrictions(view),
        insurance_requirements=_extract_insurance(view),
        default_cure_periods=_extract_cure_periods(view),
        sanitization_redactions=sanitized.redactions,
    )


__all__ = ["abstract_lease"]
