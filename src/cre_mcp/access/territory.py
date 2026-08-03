"""Territory matching for territory-limited profiles.

Grants are state codes ("TX"), exact "City, ST" strings, or exact 5-digit
zips. Location arguments arrive as any of those three forms. Unresolvable
locations are treated as outside territory (restrictive default).
"""

import re

# USPS 3-digit ZIP prefix ranges per state (contiguous conventional ranges,
# plus the notable out-of-range blocks: TX 733/885, VA 201, GA 398-399).
_STATE_ZIP3: dict[str, tuple[tuple[int, int], ...]] = {
    "AL": ((350, 369),),
    "AK": ((995, 999),),
    "AZ": ((850, 865),),
    "AR": ((716, 729),),
    "CA": ((900, 961),),
    "CO": ((800, 816),),
    "CT": ((60, 69),),
    "DE": ((197, 199),),
    "DC": ((200, 205), (569, 569)),
    "FL": ((320, 349),),
    "GA": ((300, 319), (398, 399)),
    "HI": ((967, 968),),
    "ID": ((832, 838),),
    "IL": ((600, 629),),
    "IN": ((460, 479),),
    "IA": ((500, 528),),
    "KS": ((660, 679),),
    "KY": ((400, 427),),
    "LA": ((700, 714),),
    "ME": ((39, 49),),
    "MD": ((206, 219),),
    "MA": ((10, 27), (55, 55)),
    "MI": ((480, 499),),
    "MN": ((550, 567),),
    "MS": ((386, 397),),
    "MO": ((630, 658),),
    "MT": ((590, 599),),
    "NE": ((680, 693),),
    "NV": ((889, 898),),
    "NH": ((30, 38),),
    "NJ": ((70, 89),),
    "NM": ((870, 884),),
    "NY": ((100, 149), (4, 5)),
    "NC": ((270, 289),),
    "ND": ((580, 588),),
    "OH": ((430, 459),),
    "OK": ((730, 749),),
    "OR": ((970, 979),),
    "PA": ((150, 196),),
    "RI": ((28, 29),),
    "SC": ((290, 299),),
    "SD": ((570, 577),),
    "TN": ((370, 385),),
    "TX": ((750, 799), (733, 733), (885, 885)),
    "UT": ((840, 847),),
    "VT": ((50, 59),),
    "VA": ((220, 246), (201, 201)),
    "WA": ((980, 994),),
    "WV": ((247, 268),),
    "WI": ((530, 549),),
    "WY": ((820, 831),),
    "PR": ((6, 9),),
}

_STATES = frozenset(_STATE_ZIP3)

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_STATE_RE = re.compile(r"^[A-Za-z]{2}$")
_CITY_STATE_RE = re.compile(r",\s*([A-Za-z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$")


def _state_for_zip(zip5: str) -> str | None:
    """Map a ZIP to its state, preferring the narrowest matching range.

    The table mixes broad conventional ranges with the notable out-of-range
    single-prefix exceptions (VA 201, TX 733/885, GA 398-399, MA 55, DC 569).
    An exception's span is narrower than the broad range it sits inside, so
    "smallest span wins" makes VA-201 beat DC (200-205) and TX-733 beat
    OK (730-749) regardless of table order.
    """
    prefix = int(zip5[:3])
    best_state: str | None = None
    best_span: int | None = None
    for state, ranges in _STATE_ZIP3.items():
        for low, high in ranges:
            if low <= prefix <= high:
                span = high - low
                if best_span is None or span < best_span:
                    best_span, best_state = span, state
    return best_state


def location_state(value: str) -> str | None:
    """Best-effort state extraction from a location argument."""
    text = value.strip()
    if _ZIP_RE.match(text):
        return _state_for_zip(text[:5])
    if _STATE_RE.match(text):
        code = text.upper()
        return code if code in _STATES else None
    match = _CITY_STATE_RE.search(text)
    if match:
        code = match.group(1).upper()
        return code if code in _STATES else None
    return None


def location_within(value: str, territories: tuple[str, ...]) -> bool:
    """True when the location falls inside one of the granted territories."""
    if not territories:
        return False
    granted = {t.strip().upper() for t in territories}
    if value.strip().upper() in granted:
        return True
    state = location_state(value)
    return state is not None and state in granted
