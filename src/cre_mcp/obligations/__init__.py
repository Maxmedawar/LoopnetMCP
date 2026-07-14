"""Deterministic, cited cross-document obligation screening."""

from cre_mcp.obligations.collisions import (
    Collision,
    CollisionSide,
    USE_CATEGORY_SYNONYMS,
    detect_collisions,
)
from cre_mcp.obligations.consent import (
    ConsentFatalFlag,
    ConsentRequirement,
    ConsentScreen,
    screen_transfer_consents,
)
from cre_mcp.obligations.estoppels import (
    EstoppelComparison,
    EstoppelException,
    SNDAPresence,
    compare_estoppel,
)
from cre_mcp.obligations.restrictions import RestrictionSet, extract_restrictions

__all__ = [
    "RestrictionSet",
    "extract_restrictions",
    "Collision",
    "CollisionSide",
    "USE_CATEGORY_SYNONYMS",
    "detect_collisions",
    "ConsentRequirement",
    "ConsentFatalFlag",
    "ConsentScreen",
    "screen_transfer_consents",
    "EstoppelException",
    "SNDAPresence",
    "EstoppelComparison",
    "compare_estoppel",
]
