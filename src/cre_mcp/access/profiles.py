"""The four access profiles."""

from enum import Enum


class Profile(str, Enum):
    LOCAL_SCOUT = "local_scout"
    NATIONAL_SCOUT = "national_scout"
    FULL_OPERATOR = "full_operator"
    JV_PARTNER = "jv_partner"


# Profiles whose geographic reach is limited to their granted territories.
TERRITORY_LIMITED = frozenset({Profile.LOCAL_SCOUT, Profile.JV_PARTNER})
